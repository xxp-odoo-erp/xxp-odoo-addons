# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import atexit
import logging
import os
import threading
from contextlib import contextmanager

from opentelemetry import trace

from odoo.modules.module import get_manifest

from .circuit import (
    EXPORT_PAUSE_SECONDS,
    ExportCircuit,
    GatedExporter,
    QueueBudget,
    pending_record_size,
)
from .config import get_settings
from .logging import install_root_handler, remove_root_handlers

_logger = logging.getLogger(__name__)

try:
    from opentelemetry._logs import get_logger_provider, set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        BatchLogRecordProcessor,
        LogRecordExportResult,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanLimits, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )
except ImportError as err:
    _SDK_IMPORT_ERROR = err
    _PausingSpanProcessor = None  # type: ignore
    _BudgetedLogRecordProcessor = None  # type: ignore
    _logger.debug(err)
else:
    _SDK_IMPORT_ERROR = None

    class _PausingSpanProcessor(BatchSpanProcessor):
        """Drop finished spans while the collector export is paused."""

        def __init__(self, exporter, circuit):
            super().__init__(exporter)
            self._export_circuit = circuit

        def on_end(self, span):
            context = span.context
            if context is None or not context.trace_flags.sampled:
                return None
            if not self._export_circuit.accepting():
                return None
            return super().on_end(span)

    class _BudgetedLogRecordProcessor(BatchLogRecordProcessor):
        """Admit a log record only while the queue stays within its budget."""

        def __init__(self, exporter, queue_budget, **kwargs):
            super().__init__(exporter, **kwargs)
            self._queue_budget = queue_budget

        def on_emit(self, log_record):
            if not self._queue_budget.try_acquire(pending_record_size.get()):
                return None
            return super().on_emit(log_record)


_MODULE_NAME = "xxp_otel"
_IGNORED_ENV_PREFIXES = ("OTEL_", "XXP_OTEL_")
# Time left to the batch workers to send queued data when a worker exits.
_EXIT_GRACE_SECONDS = 2.0
# Our own attributes are truncated to max_attribute_length plus a marker; the
# span limit only has to stop unbounded values such as exception messages.
_SPAN_ATTRIBUTE_HEADROOM = 1024
# Upper bound of one OTLP logs request; serialization holds it in memory twice.
_MAX_LOG_REQUEST_BYTES = 4 * 1024 * 1024


class TelemetryRuntime:
    """Process-local OpenTelemetry SDK lifecycle.

    Initialization is lazy and idempotent: exporters, their threads and the
    root logging handler are created on the first ``ensure_initialized`` call
    in a worker, never by the prefork master. The SDK batch processors restart
    their worker threads after ``fork``.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._exit_registered = False
        self._reset_local_state()
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    def ensure_initialized(self):
        """Ensure the telemetry is initialized."""
        if self._initialized:
            return True
        if self._failed:
            return False

        settings = get_settings()
        if not settings.enabled:
            # Do not initialize telemetry if it is disabled.
            return False
        if _in_prefork_master():
            # Threads, locks and the resource pid would be inherited by every
            # worker. Workers initialize on their own first request.
            return False

        with self._lock:
            if self._initialized:
                return True
            if self._failed:
                return False
            try:
                self._initialize(settings)
            except Exception:
                self._failed = True
                _logger.exception(
                    "OpenTelemetry initialization failed; "
                    "Odoo will continue without telemetry"
                )
                return False

            self._initialized = True
            return True

    def accepts_logs(self, level):
        """Return whether a record of ``level`` can reach the log exporter.

        Lets callers skip preparing payloads that would be discarded. Logger
        prefix filters are not evaluated here.
        """
        handler = self._log_handler
        if handler is None or level < handler.level:
            return False
        circuit = self._log_circuit
        return circuit is None or circuit.may_accept()

    def shutdown(self):
        with self._lock:
            remove_root_handlers()

            if self._owns_logger_provider and self._logger_provider is not None:
                try:
                    self._logger_provider.shutdown()
                except Exception:
                    _logger.exception(
                        "Failed to shut down OpenTelemetry logger provider"
                    )

            if self._owns_tracer_provider and self._tracer_provider is not None:
                try:
                    self._tracer_provider.shutdown()
                except Exception:
                    _logger.exception(
                        "Failed to shut down OpenTelemetry tracer provider"
                    )

            self._reset_local_state()

    def _shutdown_at_exit(self):
        """Flush for at most ``_EXIT_GRACE_SECONDS`` plus one in-flight export.

        The SDK's own exit hook waits up to 30 seconds per signal, delaying
        worker recycling while the collector hangs.
        """
        for circuit in (self._trace_circuit, self._log_circuit):
            if circuit is not None:
                circuit.drain(_EXIT_GRACE_SECONDS)
        self.shutdown()

    def _after_fork(self):
        self._lock = threading.RLock()
        for component in (self._trace_circuit, self._log_circuit, self._log_budget):
            if component is not None:
                component.after_fork()

    def _initialize(self, settings):
        if _SDK_IMPORT_ERROR is not None:
            raise _SDK_IMPORT_ERROR

        exporter_kwargs = {
            "headers": dict(settings.otlp_headers),
            "timeout": settings.otlp_timeout,
        }

        # Resource, providers, processors and exporters all read OTEL_* from
        # the process environment when an argument is omitted. Hide those
        # variables during setup so odoo.conf is the only configuration source.
        with _ignore_otel_environment() as ignored:
            if ignored:
                _logger.info(
                    "Ignoring OpenTelemetry environment variables; "
                    "using the Odoo config file: %s",
                    ", ".join(ignored),
                )

            resource = Resource.create(
                {
                    "service.name": settings.service_name,
                    "service.version": get_manifest(_MODULE_NAME).get("version", ""),
                    "process.pid": os.getpid(),
                }
            )

            trace_circuit = ExportCircuit(EXPORT_PAUSE_SECONDS, signal="traces")
            log_circuit = ExportCircuit(EXPORT_PAUSE_SECONDS, signal="logs")
            log_budget = QueueBudget(
                settings.log_queue_max_bytes,
                settings.log_max_queue_size,
                signal="logs",
            )
            self._trace_circuit = trace_circuit
            self._log_circuit = log_circuit
            self._log_budget = log_budget

            def build_tracer_provider():
                provider = TracerProvider(
                    resource=resource,
                    sampler=_build_sampler(settings),
                    span_limits=SpanLimits(
                        max_attribute_length=settings.max_attribute_length
                        + _SPAN_ATTRIBUTE_HEADROOM
                    ),
                    shutdown_on_exit=False,
                )
                provider.add_span_processor(
                    _PausingSpanProcessor(
                        GatedExporter(
                            OTLPSpanExporter(
                                endpoint=settings.traces_endpoint(),
                                **exporter_kwargs,
                            ),
                            trace_circuit,
                            success=SpanExportResult.SUCCESS,
                            failure=SpanExportResult.FAILURE,
                        ),
                        trace_circuit,
                    )
                )
                return provider

            def build_logger_provider():
                provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
                provider.add_log_record_processor(
                    _BudgetedLogRecordProcessor(
                        GatedExporter(
                            OTLPLogExporter(
                                endpoint=settings.logs_endpoint(),
                                **exporter_kwargs,
                            ),
                            log_circuit,
                            success=LogRecordExportResult.SUCCESS,
                            failure=LogRecordExportResult.FAILURE,
                            queue_budget=log_budget,
                            max_request_bytes=_MAX_LOG_REQUEST_BYTES,
                        ),
                        log_budget,
                        max_queue_size=settings.log_max_queue_size,
                        max_export_batch_size=min(
                            settings.log_max_export_batch_size,
                            settings.log_max_queue_size,
                        ),
                        schedule_delay_millis=settings.log_schedule_delay_ms,
                    )
                )
                return provider

            (
                self._tracer_provider,
                self._owns_tracer_provider,
            ) = _install_global_provider(
                trace.get_tracer_provider,
                trace.set_tracer_provider,
                TracerProvider,
                build_tracer_provider,
            )
            (
                self._logger_provider,
                self._owns_logger_provider,
            ) = _install_global_provider(
                get_logger_provider,
                set_logger_provider,
                LoggerProvider,
                build_logger_provider,
            )

        delegate = LoggingHandler(
            level=logging.NOTSET,
            logger_provider=self._logger_provider,
        )
        self._log_handler = install_root_handler(delegate, settings, self._log_circuit)

        if not self._exit_registered:
            atexit.register(self._shutdown_at_exit)
            self._exit_registered = True

        _logger.info(
            "OpenTelemetry initialized for process %s (service=%s)",
            os.getpid(),
            settings.service_name,
        )

    def _reset_local_state(self):
        self._initialized = False
        self._failed = False
        self._owns_tracer_provider = False
        self._owns_logger_provider = False
        self._tracer_provider = None
        self._logger_provider = None
        self._log_handler = None
        self._trace_circuit = None
        self._log_circuit = None
        self._log_budget = None


runtime = TelemetryRuntime()


def _in_prefork_master():
    from odoo.service import server as odoo_server

    current = odoo_server.server
    return isinstance(current, odoo_server.PreforkServer) and current.pid == os.getpid()


def _install_global_provider(get_global, set_global, provider_class, build):
    """Install a provider built by ``build`` unless an SDK one is already set.

    Return ``(provider, owned)``; only owned providers are shut down by us.
    """
    current = get_global()
    if isinstance(current, provider_class):
        return current, False

    candidate = build()
    set_global(candidate)
    actual = get_global()
    if actual is candidate:
        return candidate, True

    # Another component won the race for the global provider.
    candidate.shutdown()
    return actual, False


@contextmanager
def _ignore_otel_environment():
    removed = {
        key: os.environ.pop(key)
        for key in list(os.environ)
        if key.startswith(_IGNORED_ENV_PREFIXES)
    }
    try:
        yield sorted(removed)
    finally:
        os.environ.update(removed)


def _build_sampler(settings):
    name = settings.traces_sampler
    ratio = settings.traces_sampler_arg
    if name == "always_on":
        return ALWAYS_ON
    elif name == "always_off":
        return ALWAYS_OFF
    elif name == "traceidratio":
        return TraceIdRatioBased(ratio)
    elif name == "parentbased_always_off":
        return ParentBased(ALWAYS_OFF)
    elif name == "parentbased_traceidratio":
        return ParentBased(TraceIdRatioBased(ratio))
    elif name != "parentbased_always_on":
        _logger.warning(
            "Unknown otel_traces_sampler %r; using parentbased_always_on",
            settings.traces_sampler,
        )
    return ParentBased(ALWAYS_ON)

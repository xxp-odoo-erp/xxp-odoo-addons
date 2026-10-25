# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging

from .circuit import pending_record_size
from .sanitize import Sanitazed

_logger = logging.getLogger(__name__)

# The SDK and its exporters log through these loggers; exporting them would
# feed export failures back into the export queue.
_INTERNAL_LOGGER = "opentelemetry"
_INTERNAL_LOGGER_PREFIX = _INTERNAL_LOGGER + "."


class TelemetryFilter(logging.Filter):
    """Select explicitly marked records and/or configured logger prefixes."""

    def __init__(self, settings):
        super().__init__()
        prefixes = settings.log_prefixes
        self.match_all = "*" in prefixes
        self.names = frozenset(prefixes)
        self.prefixes = tuple(prefix + "." for prefix in prefixes)
        self.prefix_level = settings.log_prefix_level

    def filter(self, record):
        name = record.name
        if name == _INTERNAL_LOGGER or name.startswith(_INTERNAL_LOGGER_PREFIX):
            return False

        if record.__dict__.get("otel_event"):
            return True

        # Logger prefixes select bulk application logs; keep them above
        # ``otel_log_prefix_level`` unless explicitly lowered.
        if record.levelno < self.prefix_level:
            return False
        return self.match_all or name in self.names or name.startswith(self.prefixes)


class SafeOTelHandler(logging.Handler):
    """Fail-open adapter around OpenTelemetry's LoggingHandler."""

    _xxp_otel_handler = True

    def __init__(self, delegate, settings, export_circuit=None):
        # Logger.callHandlers() compares the handler level before filters run.
        super().__init__(level=settings.log_level)
        self.delegate = delegate
        self.settings = settings
        self._export_circuit = export_circuit
        self.addFilter(TelemetryFilter(settings))

    def emit(self, record):
        circuit = self._export_circuit
        # Drop before sanitizing. The collector is down and the queue is
        # already being discarded by the export worker.
        if circuit is not None and not circuit.accepting():
            return
        try:
            cloned, size = Sanitazed.log_record_with_size(record, self.settings)
            token = pending_record_size.set(size)
            try:
                self.delegate.emit(cloned)
            finally:
                pending_record_size.reset(token)
        except Exception:
            # Telemetry is non-critical. Never affect the Odoo request because
            # formatting/export of a log record failed.
            return

    def close(self):
        try:
            self.delegate.close()
        except Exception:
            _logger.debug(
                "Failed to close OpenTelemetry logging handler", exc_info=True
            )
        return super().close()


def install_root_handler(delegate, settings, export_circuit=None):
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_xxp_otel_handler", False):
            return handler

    handler = SafeOTelHandler(delegate, settings, export_circuit)
    root.addHandler(handler)
    return handler


def remove_root_handlers():
    root = logging.getLogger()
    for handler in list(root.handlers):
        if not getattr(handler, "_xxp_otel_handler", False):
            continue
        root.removeHandler(handler)
        handler.close()

# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import functools
import inspect
import logging

from opentelemetry import trace

from .config import get_settings
from .runtime import runtime
from .sanitize import Capture, record_span_exception
from .tools import recordset_ids

_logger = logging.getLogger(__name__)

_DEFAULT_EVENT = "odoo.method.call"
_SPAN_ATTRIBUTES = ("odoo.model", "odoo.record_count", "odoo.uid", "odoo.company_id")


class ObserveMethod:
    """Trace an Odoo/Python method and export sanitized call arguments.

    Fail-open: when telemetry is disabled or initialization fails, the wrapped
    method is called directly and its result or exceptions are not altered.

    ``self``/``cls`` are excluded from captured arguments. For Odoo recordsets,
    model/record/user/company context is exported separately.
    """

    def __init__(
        self,
        *,
        event=_DEFAULT_EVENT,
        span_name=None,
        capture_arguments=True,
        capture_result=False,
        level=logging.INFO,
    ):
        self.event = event
        self.span_name = span_name
        self.capture_arguments = capture_arguments
        self.capture_result = capture_result
        self.level = level

    def __call__(self, method):
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            signature = None
        logger = logging.getLogger(method.__module__)
        tracer = trace.get_tracer(method.__module__)
        qualified_name = f"{method.__module__}.{method.__qualname__}"

        def arguments_capture(args, kwargs):
            return Capture(
                "arguments",
                factory=functools.partial(_bind_arguments, signature, args, kwargs),
            )

        # Return a plain function so Odoo model methods still bind ``self``.
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            if not runtime.ensure_initialized():
                return method(*args, **kwargs)

            settings = get_settings()
            context = _get_odoo_context(
                args[0] if args else None, settings.max_collection_items
            )
            model_name = context.get("odoo.model")
            span_name = self.span_name or (
                f"{model_name}.{method.__name__}" if model_name else qualified_name
            )
            # Values are sanitized once, by the exporting handler, and only
            # when the record is actually exported.
            extra = dict(context)
            extra["otel.method"] = qualified_name

            # The SDK would export str(exc) and the traceback unsanitized.
            with tracer.start_as_current_span(
                span_name, record_exception=False, set_status_on_exception=False
            ) as span:
                if span.is_recording():
                    span.set_attribute("odoo.method", method.__name__)
                    for key in _SPAN_ATTRIBUTES:
                        if context.get(key) is not None:
                            span.set_attribute(key, context[key])

                call_extra = dict(extra, otel_event=self.event)
                if logger.isEnabledFor(self.level):
                    if self.capture_arguments and runtime.accepts_logs(self.level):
                        call_extra["odoo.capture"] = arguments_capture(args, kwargs)  # type: ignore
                    logger.log(
                        self.level,
                        "Observed method call: %s",
                        qualified_name,
                        extra=call_extra,
                    )
                try:
                    result = method(*args, **kwargs)
                except Exception as exc:
                    record_span_exception(span, exc, settings)
                    call_extra["otel_event"] = "%s.error" % self.event
                    if (
                        self.capture_arguments
                        and "odoo.capture" not in call_extra
                        and runtime.accepts_logs(logging.ERROR)
                    ):
                        call_extra["odoo.capture"] = arguments_capture(args, kwargs)  # type: ignore
                    logger.exception(
                        "Observed method failed: %s", qualified_name, extra=call_extra
                    )
                    raise

                if self.capture_result and logger.isEnabledFor(self.level):
                    extra["otel_event"] = "%s.result" % self.event
                    if runtime.accepts_logs(self.level):
                        extra["odoo.capture"] = Capture("result", result)
                    logger.log(
                        self.level,
                        "Observed method completed: %s",
                        qualified_name,
                        extra=extra,
                    )
                return result

        return wrapper


observe_method = ObserveMethod


def _bind_arguments(signature, args, kwargs):
    """Return arguments keyed by parameter name, excluding self/cls."""
    if signature is not None:
        try:
            arguments = dict(signature.bind_partial(*args, **kwargs).arguments)
        except TypeError:
            # Observability must never make an otherwise valid call fail.
            _logger.debug("Cannot bind call arguments to %s", signature, exc_info=True)
        else:
            arguments.pop("self", None)
            arguments.pop("cls", None)
            return arguments

    fallback = {"args": args[1:], "kwargs": kwargs}
    return {key: value for key, value in fallback.items() if value}


def _get_odoo_context(receiver, max_ids=100):
    """Return the identity of ``receiver`` when it is an Odoo recordset."""
    context = {}
    model_name = getattr(receiver, "_name", None)
    if model_name:
        context["odoo.model"] = str(model_name)

    raw_ids = getattr(receiver, "_ids", None)
    if isinstance(raw_ids, tuple):
        context["odoo.record_ids"] = recordset_ids(receiver, max_ids)
        context["odoo.record_count"] = len(raw_ids)
    else:
        record_ids = getattr(receiver, "ids", None)
        if isinstance(record_ids, list):
            context["odoo.record_ids"] = record_ids[:max_ids]
            context["odoo.record_count"] = len(record_ids)

    env = getattr(receiver, "env", None)
    if env is not None:
        try:
            context["odoo.uid"] = env.uid
            context["odoo.company_id"] = env.company.id
        except Exception:
            # Invalid allowed_company_ids in the context raises AccessError.
            _logger.debug("Cannot read Odoo user/company context", exc_info=True)
    return context

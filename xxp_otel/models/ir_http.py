# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind, Status, StatusCode

from odoo import models
from odoo.http import request

from ..telemetry.config import get_settings, should_trace_http_route
from ..telemetry.runtime import runtime
from ..telemetry.sanitize import Sanitazed, record_span_exception

_tracer = trace.get_tracer(__name__)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        # Store the route for later use in _dispatch().
        request._otel_route = rule.rule  # type: ignore
        return super()._pre_dispatch(rule, args)

    @classmethod
    def _dispatch(cls, endpoint):
        # Skip the rest of the method when telemetry is disabled.
        if not runtime.ensure_initialized():
            return super()._dispatch(endpoint)

        settings = get_settings()
        # Skip the rest of the method when HTTP tracing is disabled.
        if not settings.trace_http:
            return super()._dispatch(endpoint)

        http_request = request.httprequest
        path = http_request.path
        route = getattr(request, "_otel_route", None) or path
        # Skip the rest of the method when the route is not traced.
        if not should_trace_http_route(route, path, settings):
            return super()._dispatch(endpoint)

        try:
            parent_context = extract(http_request.headers)
        except Exception:
            # Malformed propagation headers must never break an Odoo request.
            parent_context = None

        method = http_request.method
        # The SDK would export str(exc) and the traceback unsanitized.
        with _tracer.start_as_current_span(
            f"{method} {route}",
            context=parent_context,
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": method,
                "http.route": route,
                "url.path": path,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            # Skip attribute work (and a possible SQL query) for sampled-out spans.
            if span.is_recording():
                span.set_attributes(_odoo_request_attributes(endpoint, settings))

            try:
                result = super()._dispatch(endpoint)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                record_span_exception(span, exc, settings)
                raise

            # JSON-RPC endpoints return plain values; the Response is built later.
            status_code = getattr(result, "status_code", None)
            if isinstance(status_code, int):
                span.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))

            return result


def _odoo_request_attributes(endpoint, settings):
    """
    Prepare attribute for the Odoo request

    Args:
        endpoint: The endpoint to be dispathed
        settings: The settings for the telemetry

    Returns:
        A dictionary of attributes for the Odoo request
    """
    attributes = {
        "odoo.db": request.db,
        "odoo.request.type": endpoint.routing["type"],
    }

    env = request.env
    # uid is None for auth="none" routes.
    if env.uid:
        attributes["odoo.uid"] = env.uid
        try:
            company_id = env.company.id
        except Exception:
            # Invalid allowed_company_ids in the context raises AccessError.
            company_id = None
        if company_id:
            attributes["odoo.company_id"] = company_id

    params = getattr(request, "params", None)
    if settings.trace_rpc and isinstance(params, Mapping):
        # /web/dataset/call_kw parameters are already parsed by Odoo here.
        model = params.get("model")
        method = params.get("method")
        if isinstance(model, str):
            attributes["odoo.model"] = model
        if isinstance(method, str):
            attributes["odoo.method"] = method

    if settings.capture_request_params:
        # Span attributes are scalars. The sanitized params are one JSON string.
        encoded = encode_request_params(params, settings)
        if encoded:
            attributes["odoo.request.params"] = encoded

    return attributes


def encode_request_params(params, settings):
    """Return sanitized request params as a bounded JSON string.

    Args:
        params: The request parameters
        settings: The settings for the telemetry

    Returns:
        A sanitized JSON string of the request parameters
    """
    if not isinstance(params, Mapping) or not params:
        return None
    try:
        # The budget stops walking large ``write`` payloads once the
        # attribute limit is reached.
        return Sanitazed.json(params, settings, settings.max_attribute_length)
    except Exception:
        return None

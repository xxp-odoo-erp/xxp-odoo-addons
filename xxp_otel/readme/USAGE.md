## For developers

The module already exports the standard Odoo logs and traces.

You can extend the traced data. To do this, customize a technical module.

The sections below show the procedures.

## 1. Log an event

```python
import logging

_logger = logging.getLogger(__name__)  # the standard Odoo logger

_logger.info(
    "External API request completed",  # short text, no payload here
    extra={
        "otel_event": "integration.response",  # always export this record
        "integration.name": "external_api",
        "request_payload": request_payload,  # dict or JSON string
        "response_payload": response.json(),  # secrets become "***"
    },
)
```

## 2. Add a span

```python
from opentelemetry import trace  # no dependency on xxp_otel

tracer = trace.get_tracer(__name__)


def action_confirm(self):
    # works even if xxp_otel is not installed
    with tracer.start_as_current_span("sale.order.confirm"):
        return super().action_confirm()
```

## 3. Trace a method

```python
from odoo.addons.xxp_otel.telemetry import observe_method  # depends on xxp_otel


class ResPartner(models.Model):
    _inherit = "res.partner"

    @observe_method(  # span + log record with the arguments
        event="integration.external_api.response",  # optional
        span_name="external_api.document.get",  # optional
        capture_result=True,  # also log the result (default: False)
    )
    def _get_external_document(self, document_id):
        ...
```

**Tip:** Put code that uses `observe_method` into a separate addon, for example
`xxp_otel_sale`, so the business module can install without `xxp_otel`.

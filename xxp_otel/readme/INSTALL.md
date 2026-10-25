## Python dependencies

Install these Python packages in the Odoo environment:

- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp-proto-http`
- `opentelemetry-instrumentation-logging`

**Note:** `requirements.txt` file contains these packages:

```bash
pip install -r requirements.txt
```

## Module installation

1. Add the repository directory to `addons_path`.
2. Restart Odoo.
3. Install the `xxp_otel` module.

## Observability backend

The module does not depend on a specific vendor.
The module needs a receiver that accepts OTLP/HTTP. You can use the OpenTelemetry
Collector or an observability backend with OTLP/HTTP ingestion. 

Install the receiver on a server that is not the Odoo or PostgreSQL server.

**Warning:** Do not open the OTLP ingestion port to the internet. Open it only to the
Odoo servers.

Before you use the receiver in production, do a check of these items:

- Network and firewall rules.
- Authentication of the OTLP ingestion.
- Data retention.
- CPU, RAM and disk sizing.

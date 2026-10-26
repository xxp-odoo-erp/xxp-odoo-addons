This module sends OpenTelemetry data from Odoo to an external collector.

OpenTelemetry (OTel) is an open standard for traces, logs and metrics. 

Module's core features:
- Sends the data with the OpenTelemetry Protocol (OTLP) over HTTP
(OTLP/HTTP).
- Operates in "fail-open" mode. An OpenTelemetry error does not change the
result or the exception of a business operation.
- Hides sensetive data in logs and traces.
- The module does not create database tables for telemetry data. 

The module exports these signals:

- Traces of incoming HTTP requests.
- Selected records of the standard Python `logging` module.
- Structured events of integrations.
- Spans for specified methods. You can create these spans manually or with a
  decorator.

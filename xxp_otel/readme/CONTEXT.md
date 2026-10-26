Odoo has no built-in tools to analyze logs or traces. It only writes plain text
lines to a log file (set by the `logfile` option in `odoo.conf`) or, if this
option is empty, to stdout. This output has several limits:

- The lines are unstructured text, so they are hard to search and filter.
- The lines are not linked to a request or an operation, so you cannot see
  everything that happened during one call.
- Old files are usually rotated and deleted by an external tool, so the history
  is short.

Because of this, integration modules often store their own technical logs in
Odoo models: raw HTTP requests and responses, webhook calls, and so on. These
records are not business data, but they grow the PostgreSQL database and make
it slower.

This module solves both problems. It sends traces and structured logs to an
external observability system using OpenTelemetry. Each log record is linked to
the request or operation that produced it, and the Odoo database keeps only
business data.
# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).
{
    "name": "XXP Odoo OpenTelemetry",
    "summary": "OpenTelemetry tracing and structured log export for Odoo",
    "version": "16.0.1.0.0",
    "category": "Technical",
    "author": "XXP",
    "license": "LGPL-3",
    "website": "https://xxp-odoo.com",
    "depends": ["base"],
    "external_dependencies": {
        "python": [
            "opentelemetry-api",
            "opentelemetry-sdk",
            "opentelemetry-exporter-otlp-proto-http",
            "opentelemetry-instrumentation-logging",
        ],
    },
    "installable": True,
    "uninstall_hook": "uninstall_hook",
}

# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import dataclasses
import logging

from ..telemetry.logging import SafeOTelHandler, TelemetryFilter
from .common import TestOTELCOmmon


class TestTelemetryFilter(TestOTELCOmmon):
    def setUp(self):
        super().setUp()
        self.settings = self.build_settings(
            enabled=True,
            trace_http=True,
            trace_rpc=True,
            service_name="odoo-test",
            log_level=logging.INFO,
            log_prefixes=("odoo.addons.my_integration",),
            max_message_length=1024,
            max_attribute_length=1024,
            max_collection_items=10,
            redact_keys=("token", "password"),
        )

    def test_explicit_event_is_exported(self):
        """Test that explicit event is exported."""
        log_filter = TelemetryFilter(self.settings)
        self.assertTrue(
            log_filter.filter(self._record(name="custom.module", otel_event=True)),
            "Record should be filtered",
        )

    def test_prefix_is_exported(self):
        """Test that prefix is exported."""
        log_filter = TelemetryFilter(self.settings)
        self.assertTrue(
            log_filter.filter(
                self._record(
                    name="odoo.addons.my_integration.models.sale_order",
                    level=logging.WARNING,
                )
            ),
            "Record should be filtered",
        )

    def test_bulk_info_logs_need_explicit_prefix_level(self):
        """Test that bulk info logs need explicit prefix level."""
        name = "odoo.addons.my_integration.models.sale_order"
        self.assertFalse(TelemetryFilter(self.settings).filter(self._record(name=name)))

        lowered = dataclasses.replace(self.settings, log_prefix_level=logging.INFO)
        self.assertTrue(TelemetryFilter(lowered).filter(self._record(name=name)))

    def test_events_ignore_prefix_level(self):
        """Test that events ignore prefix level."""
        log_filter = TelemetryFilter(self.settings)
        self.assertTrue(
            log_filter.filter(
                self._record(name="odoo.addons.my_integration", otel_event="x"),
            ),
            "Record should be filtered",
        )

    def test_unrelated_log_is_ignored(self):
        """Test that unrelated log is ignored."""
        log_filter = TelemetryFilter(self.settings)
        self.assertFalse(
            log_filter.filter(self._record(name="odoo.sql_db")),
            "Record should be filtered",
        )

    def test_prefix_matches_logger_boundary(self):
        """Test that prefix matches logger boundary."""
        log_filter = TelemetryFilter(self.settings)
        self.assertTrue(
            log_filter.filter(
                self._record(name="odoo.addons.my_integration", level=logging.ERROR),
            ),
            "Record should be filtered",
        )
        self.assertFalse(
            log_filter.filter(
                self._record(
                    name="odoo.addons.my_integration_extra", level=logging.ERROR
                )
            ),
            "Record should not be filtered",
        )

    def test_sdk_logs_are_never_exported(self):
        """Test that SDK logs are never exported."""
        settings = dataclasses.replace(self.settings, log_prefixes=("*",))
        log_filter = TelemetryFilter(settings)
        self.assertTrue(
            log_filter.filter(self._record(name="odoo.sql_db", level=logging.WARNING)),
            "Record should be filtered",
        )
        self.assertFalse(
            log_filter.filter(
                self._record(name="opentelemetry.sdk._shared_internal", otel_event=True)
            ),
            "Record should not be filtered",
        )

    def test_handler_level_follows_settings(self):
        """Test that handler level follows settings."""
        settings = dataclasses.replace(self.settings, log_level=logging.WARNING)
        handler = SafeOTelHandler(delegate=logging.NullHandler(), settings=settings)
        self.assertEqual(
            handler.level, logging.WARNING, "Handler level should be WARNING"
        )

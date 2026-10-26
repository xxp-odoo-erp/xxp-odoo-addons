# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging
import os

from odoo.tests.common import BaseCase
from odoo.tools import config as odoo_config

from ..telemetry.config import (
    SettingsBuilder,
    clear_settings_cache,
    get_settings,
    should_trace_http_route,
)


class TestSettingsFromOdooConfig(BaseCase):
    def setUp(self):
        super().setUp()
        self._saved_options = dict(odoo_config.options)
        self._saved_env = {
            key: os.environ[key]
            for key in list(os.environ)
            if key.startswith("OTEL_") or key.startswith("XXP_OTEL_")
        }
        for key in self._saved_env:
            del os.environ[key]
        clear_settings_cache()

    def tearDown(self):
        odoo_config.options.clear()
        odoo_config.options.update(self._saved_options)
        for key in list(os.environ):
            if key.startswith("OTEL_") or key.startswith("XXP_OTEL_"):
                del os.environ[key]
        os.environ.update(self._saved_env)
        clear_settings_cache()
        super().tearDown()

    def test_defaults_when_options_are_absent(self):
        """Test that defaults are used when options are absent."""
        for key in list(odoo_config.options):
            if key.startswith("otel_"):
                del odoo_config.options[key]

        settings = get_settings()

        self.assertFalse(settings.enabled, "Enabled should be False")
        self.assertTrue(settings.trace_http, "Trace HTTP should be True")
        self.assertTrue(settings.trace_rpc, "Trace RPC should be True")
        self.assertEqual(settings.service_name, "odoo", "Service name should be 'odoo'")
        self.assertEqual(
            settings.traces_endpoint(),
            "http://localhost:4318/v1/traces",
            "Traces endpoint should be 'http://localhost:4318/v1/traces'",
        )
        self.assertEqual(
            settings.logs_endpoint(),
            "http://localhost:4318/v1/logs",
            "Logs endpoint should be 'http://localhost:4318/v1/logs'",
        )

    def test_production_defaults(self):
        """Test that production defaults are used when options are absent."""
        settings = SettingsBuilder({}).build()

        self.assertEqual(
            settings.traces_sampler,
            "parentbased_traceidratio",
            "Traces sampler should be 'parentbased_traceidratio'",
        )
        self.assertEqual(
            settings.traces_sampler_arg, 0.1, "Traces sampler arg should be 0.1"
        )
        self.assertFalse(
            settings.capture_request_params, "Capture request params should be False"
        )
        self.assertEqual(
            settings.trace_exclude_routes,
            ("/websocket", "/longpolling"),
            "Trace exclude routes should be ('/websocket', '/longpolling')",
        )
        self.assertFalse(
            should_trace_http_route("/websocket", "/websocket", settings),
            "Should trace HTTP route should be False",
        )
        self.assertEqual(settings.log_level, logging.INFO, "Log level should be INFO")
        self.assertEqual(
            settings.log_prefix_level,
            logging.WARNING,
            "Log prefix level should be WARNING",
        )
        self.assertEqual(settings.max_depth, 6, "Max depth should be 6")
        self.assertEqual(
            settings.max_event_bytes, 256 * 1024, "Max event bytes should be 256 * 1024"
        )
        self.assertEqual(
            settings.log_queue_max_bytes,
            32 * 1024 * 1024,
            "Log queue max bytes should be 32 * 1024 * 1024",
        )
        self.assertEqual(
            settings.log_max_queue_size, 2048, "Log max queue size should be 2048"
        )
        self.assertEqual(
            settings.log_max_export_batch_size,
            64,
            "Log max export batch size should be 64",
        )
        self.assertEqual(
            settings.log_schedule_delay_ms, 200, "Log schedule delay ms should be 200"
        )

    def test_memory_options_are_read(self):
        """Test that memory options are read."""
        settings = SettingsBuilder(
            {
                "otel_log_prefix_level": "info",
                "otel_max_depth": "3",
                "otel_max_event_bytes": "65536",
                "otel_log_queue_max_bytes": "1",
                "otel_log_max_queue_size": "512",
                "otel_log_max_export_batch_size": "32",
                "otel_log_schedule_delay": "10",
                "otel_trace_exclude_routes": "/websocket,/web/static",
                "otel_capture_request_params": True,
            }
        ).build()

        self.assertEqual(
            settings.log_prefix_level, logging.INFO, "Log prefix level should be INFO"
        )
        self.assertEqual(settings.max_depth, 3, "Max depth should be 3")
        self.assertEqual(
            settings.max_event_bytes, 65536, "Max event bytes should be 65536"
        )
        self.assertEqual(
            settings.log_queue_max_bytes,
            1024 * 1024,
            "Log queue max bytes should be 1024 * 1024",
        )
        self.assertEqual(
            settings.log_max_queue_size, 512, "Log max queue size should be 512"
        )
        self.assertEqual(
            settings.log_max_export_batch_size,
            32,
            "Log max export batch size should be 32",
        )
        self.assertEqual(
            settings.log_schedule_delay_ms, 50, "Log schedule delay ms should be 50"
        )
        self.assertEqual(
            settings.trace_exclude_routes,
            ("/websocket", "/web/static"),
            "Trace exclude routes should be ('/websocket', '/web/static')",
        )
        self.assertTrue(
            settings.capture_request_params, "Capture request params should be True"
        )

    def test_options_are_read_from_odoo_config(self):
        """Test that options are read from Odoo config."""
        # Odoo converts the words true/false while loading the config file.
        odoo_config.options.update(
            {
                "otel_enabled": True,
                "otel_trace_http": False,
                "otel_service_name": "odoo-test",
                "otel_log_prefixes": "odoo.addons.my_integration, odoo.addons.web",
                "otel_otlp_endpoint": "http://collector:4318/",
                "otel_otlp_traces_endpoint": "http://collector:4318/v1/traces",
                "otel_otlp_headers": "Authorization=Bearer secret",
                "otel_otlp_timeout": "15",
                "otel_traces_sampler": "parentbased_traceidratio",
                "otel_traces_sampler_arg": "0.10",
                "otel_redact_keys": "private_key",
            }
        )

        settings = get_settings()

        self.assertTrue(settings.enabled, "Enabled should be True")
        self.assertFalse(settings.trace_http, "Trace HTTP should be False")
        self.assertEqual(
            settings.service_name, "odoo-test", "Service name should be 'odoo-test'"
        )
        self.assertEqual(
            settings.log_prefixes,
            ("odoo.addons.my_integration", "odoo.addons.web"),
            "Log prefixes should be ('odoo.addons.my_integration', 'odoo.addons.web')",
        )
        self.assertEqual(
            settings.traces_endpoint(),
            "http://collector:4318/v1/traces",
            "Traces endpoint should be 'http://collector:4318/v1/traces'",
        )
        self.assertEqual(
            settings.logs_endpoint(),
            "http://collector:4318/v1/logs",
            "Logs endpoint should be 'http://collector:4318/v1/logs'",
        )
        self.assertEqual(
            settings.otlp_headers,
            (("Authorization", "Bearer secret"),),
            "OTLP headers should be (('Authorization', 'Bearer secret'),)",
        )
        self.assertEqual(settings.otlp_timeout, 15.0, "OTLP timeout should be 15.0")
        self.assertEqual(
            settings.traces_sampler,
            "parentbased_traceidratio",
            "Traces sampler should be 'parentbased_traceidratio'",
        )
        self.assertEqual(
            settings.traces_sampler_arg, 0.10, "Traces sampler arg should be 0.10"
        )
        self.assertIn(
            "private_key", settings.redact_keys, "Private key should be in redact keys"
        )
        self.assertIn(
            "password", settings.redact_keys, "Password should be in redact keys"
        )

    def test_builder_sanitizes_invalid_values(self):
        """Test that builder sanitizes invalid values."""
        settings = SettingsBuilder(
            {
                "otel_enabled": "yes",
                "otel_log_level": "basicConfig",
                "otel_max_message_length": "10",
                "otel_max_collection_items": "many",
                "otel_otlp_headers": "X-Key = value, broken, =empty",
                "otel_traces_sampler_arg": "5",
            }
        ).build()

        self.assertTrue(settings.enabled, "Enabled should be True")
        self.assertEqual(settings.log_level, logging.INFO, "Log level should be INFO")
        self.assertEqual(
            settings.max_message_length, 256, "Max message length should be 256"
        )
        self.assertEqual(
            settings.max_collection_items, 100, "Max collection items should be 100"
        )
        self.assertEqual(
            settings.otlp_headers,
            (("X-Key", "value"),),
            "OTLP headers should be (('X-Key', 'value'),)",
        )
        self.assertEqual(
            settings.traces_sampler_arg, 1.0, "Traces sampler arg should be 1.0"
        )

    def test_environment_variables_are_ignored(self):
        """Test that environment variables are ignored."""
        for key in list(odoo_config.options):
            if key.startswith("otel_"):
                del odoo_config.options[key]
        os.environ["XXP_OTEL_ENABLED"] = "true"
        os.environ["OTEL_SERVICE_NAME"] = "from-env"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://env:4318"

        settings = get_settings()

        self.assertFalse(settings.enabled, "Enabled should be False")
        self.assertEqual(settings.service_name, "odoo", "Service name should be 'odoo'")
        self.assertEqual(
            settings.traces_endpoint(),
            "http://localhost:4318/v1/traces",
            "Traces endpoint should be 'http://localhost:4318/v1/traces'",
        )

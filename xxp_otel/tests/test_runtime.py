# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging
import os
import time
from unittest.mock import MagicMock, patch

from opentelemetry._logs import LogRecord
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import LogRecordExportResult

from odoo.service import server as odoo_server

from ..telemetry.circuit import ExportCircuit, GatedExporter, QueueBudget
from ..telemetry.config import SettingsBuilder
from ..telemetry.runtime import (
    TelemetryRuntime,
    _BudgetedLogRecordProcessor,
    _build_sampler,
    _in_prefork_master,
)
from .common import TestOTELCOmmon


class TestRuntime(TestOTELCOmmon):
    def test_master_is_detected_by_pid(self):
        """Test that the master is detected by PID."""
        with patch.object(odoo_server, "server", self._prefork_server(os.getpid())):
            self.assertTrue(_in_prefork_master(), "Master should be detected by PID")
        with patch.object(odoo_server, "server", self._prefork_server(os.getpid() + 1)):
            self.assertFalse(
                _in_prefork_master(), "Master should not be detected by PID + 1"
            )
        with patch.object(odoo_server, "server", None):
            self.assertFalse(
                _in_prefork_master(), "Master should not be detected by None"
            )

    def test_master_does_not_initialize_and_does_not_fail(self):
        """Test that the master does not initialize and does not fail."""
        telemetry = TelemetryRuntime()
        settings = SettingsBuilder({"otel_enabled": True}).build()
        with (
            patch(
                "odoo.addons.xxp_otel.telemetry.config.get_settings",
                return_value=settings,
            ),
            patch.object(odoo_server, "server", self._prefork_server(os.getpid())),
            patch.object(telemetry, "_initialize") as initialize,
        ):
            self.assertFalse(
                telemetry.ensure_initialized(), "Telemetry should not be initialized"
            )

        initialize.assert_not_called()
        self.assertFalse(telemetry._failed, "Telemetry should not have failed")

    def test_default_sampler_keeps_ten_percent(self):
        sampler = _build_sampler(SettingsBuilder({}).build())
        self.assertIn(
            "TraceIdRatioBased{0.1}",
            sampler.get_description(),
            "Sampler should be a TraceIdRatioBased with 0.1",
        )

    def test_accepts_logs_follows_handler_level_and_circuit(self):
        """Test that accepts_logs follows handler level and circuit."""
        telemetry = TelemetryRuntime()
        self.assertFalse(
            telemetry.accepts_logs(logging.ERROR),
            "Telemetry should not accept logs at ERROR level",
        )

        telemetry._log_handler = MagicMock(level=logging.WARNING)
        telemetry._log_circuit = ExportCircuit(30)
        self.assertFalse(
            telemetry.accepts_logs(logging.INFO),
            "Telemetry should not accept logs at INFO level",
        )
        self.assertTrue(
            telemetry.accepts_logs(logging.ERROR),
            "Telemetry should accept logs at ERROR level",
        )

        with self.assertLogs("odoo.addons.xxp_otel.telemetry.circuit", "WARNING"):
            telemetry._log_circuit.note_failure()
        self.assertFalse(
            telemetry.accepts_logs(logging.ERROR),
            "Telemetry should not accept logs at ERROR level",
        )

    def test_after_fork_resets_circuits_and_budget(self):
        """Test that after_fork resets circuits and budget."""
        telemetry = TelemetryRuntime()
        telemetry._log_circuit = ExportCircuit(30)
        telemetry._log_budget = QueueBudget(100, 10)
        telemetry._log_budget.try_acquire(50)
        with self.assertLogs("odoo.addons.xxp_otel.telemetry.circuit", "WARNING"):
            telemetry._log_circuit.note_failure()

        telemetry._after_fork()

        self.assertTrue(
            telemetry._log_circuit.accepting(),
            "Telemetry should be accepting logs after fork",
        )
        self.assertEqual(
            telemetry._log_budget.queued_bytes,
            0,
            "Telemetry should have reset the budget",
        )

    def test_drained_shutdown_does_not_wait_for_every_batch(self):
        """Test that drained shutdown does not wait for every batch."""
        exporter = self._slow_exporter(delay=0.5)
        circuit = ExportCircuit(30)
        budget = QueueBudget(10**9, 4096)
        processor = _BudgetedLogRecordProcessor(
            GatedExporter(
                exporter,
                circuit,
                success=LogRecordExportResult.SUCCESS,
                failure=LogRecordExportResult.FAILURE,
                queue_budget=budget,
            ),
            budget,
            max_queue_size=4096,
            max_export_batch_size=8,
        )
        provider = LoggerProvider(shutdown_on_exit=False)
        provider.add_log_record_processor(processor)
        logger = provider.get_logger("test")
        for _index in range(400):
            logger.emit(LogRecord(body="x"))

        started = time.monotonic()
        circuit.drain(0.2)
        provider.shutdown()
        elapsed = time.monotonic() - started

        # Without draining, 50 batches would take 25 seconds.
        self.assertLess(
            elapsed, 2.0, "Drained shutdown should take less than 2 seconds"
        )
        self.assertLess(
            exporter.calls, 5, "Drained shutdown should export less than 5 batches"
        )

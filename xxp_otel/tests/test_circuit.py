# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging

from ..telemetry import circuit as circuit_module
from ..telemetry.circuit import ExportCircuit, GatedExporter
from ..telemetry.logging import SafeOTelHandler
from .common import TestOTELCOmmon


class TestExportCircuit(TestOTELCOmmon):
    def setUp(self):
        super().setUp()
        self.circuit = ExportCircuit(30, clock=self.clock, signal="logs")
        self.gated = GatedExporter(
            self.exporter,
            self.circuit,
            success="ok",
            failure="dropped",
        )

    def test_closed_circuit_accepts_records_and_exports(self):
        """Test that closed circuit accepts records and exports."""
        self.assertTrue(self.circuit.accepting(), "Circuit should be accepting")
        self.assertTrue(self.circuit.accepting(), "Circuit should be accepting")
        self.assertTrue(self.circuit.allow_export(), "Circuit should allow export")

    def test_failure_pauses_until_retry_then_admits_one_probe(self):
        """Test that failure pauses until retry then admits one probe."""
        with self.assertLogs(circuit_module.__name__, level="WARNING") as logs:
            self.circuit.note_failure()

        self.assertIn("paused", logs.output[0], "Paused message should be in logs")
        self.assertFalse(self.circuit.accepting(), "Circuit should not be accepting")
        self.assertFalse(self.circuit.allow_export(), "Circuit should not allow export")

        with self.assertNoLogs(circuit_module.__name__, level="WARNING"):
            self.circuit.note_failure()

        self.clock.now = 30
        self.assertTrue(self.circuit.accepting(), "Circuit should be accepting")
        self.assertFalse(
            self.circuit.accepting(), "Circuit should not be accepting after retry"
        )
        self.assertTrue(
            self.circuit.allow_export(), "Circuit should allow export after retry"
        )
        self.assertFalse(
            self.circuit.allow_export(), "Circuit should not allow export after retry"
        )

    def test_successful_probe_resumes_export(self):
        """Test that successful probe resumes export."""
        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            self.circuit.note_failure()
        self.clock.now = 30
        self.circuit.allow_export()

        with self.assertLogs(circuit_module.__name__, level="INFO") as logs:
            self.circuit.note_success()

        self.assertIn("resumed", logs.output[0], "Resumed message should be in logs")
        self.assertTrue(self.circuit.accepting(), "Circuit should be accepting")
        self.assertTrue(self.circuit.allow_export(), "Circuit should allow export")

    def test_success_reaches_the_collector(self):
        """Test that success reaches the collector."""
        self.assertEqual(
            self.gated.export(["row"]), "ok", "Export row should be equal to 'ok'"
        )
        self.assertEqual(
            self.exporter.calls,
            [["row"]],
            "Exporter calls should be equal to [['row']]",
        )

    def test_failure_drops_later_batches_without_a_network_call(self):
        """Test that failure drops later batches without a network call."""
        self.exporter.result = "no"

        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            self.assertEqual(
                self.gated.export(["row"]), "no", "Export row should be equal to 'no'"
            )

        self.assertEqual(
            self.gated.export(["later"]),
            "dropped",
            "Export later should be equal to 'dropped'",
        )
        self.assertEqual(
            self.exporter.calls,
            [["row"]],
            "Exporter calls should be equal to [['row']]",
        )

        self.clock.now = 30
        self.exporter.result = "ok"
        with self.assertLogs(circuit_module.__name__, level="INFO"):
            self.assertEqual(
                self.gated.export(["probe"]),
                "ok",
                "Export probe should be equal to 'ok'",
            )

        self.assertEqual(
            self.exporter.calls[-1],
            ["probe"],
            "Exporter calls should be equal to [['probe']]",
        )
        self.assertTrue(self.circuit.accepting(), "Circuit should be accepting")

    def test_exception_pauses_the_circuit(self):
        """Test that exception pauses the circuit."""
        self.exporter.error = RuntimeError("collector down")  # type: ignore

        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            with self.assertRaises(RuntimeError):
                self.gated.export(["row"])

        self.assertEqual(
            self.gated.export(["later"]),
            "dropped",
            "Export later should be equal to 'dropped'",
        )
        self.assertEqual(
            len(self.exporter.calls), 1, "Exporter calls should be equal to 1"
        )

    def test_shutdown_reaches_the_delegate(self):
        """Test that shutdown reaches the delegate."""
        self.gated.shutdown()
        self.assertEqual(
            self.exporter.shutdowns, 1, "Exporter shutdowns should be equal to 1"
        )

    def test_paused_circuit_skips_sanitization_and_export(self):
        """Test that paused circuit skips sanitization and export."""
        settings = self.build_settings(
            enabled=True,
            trace_http=True,
            trace_rpc=True,
            service_name="odoo-test",
            log_level=logging.INFO,
            log_prefixes=("odoo.addons.my_integration",),
            max_message_length=1024,
            max_attribute_length=1024,
            max_collection_items=10,
            redact_keys=("token",),
        )
        clock = self.clock
        circuit = ExportCircuit(30, clock=self.clock, signal="logs")
        sink = self._sink()
        handler = SafeOTelHandler(sink, settings, circuit)
        record = self._record(
            name="odoo.addons.my_integration",
            msg="message",
        )

        handler.emit(record)
        self.assertEqual(len(sink.records), 1, "Sink records should be equal to 1")

        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            circuit.note_failure()
        handler.emit(record)
        self.assertEqual(len(sink.records), 1, "Sink records should be equal to 1")

        clock.now = 30
        handler.emit(record)
        handler.emit(record)
        self.assertEqual(len(sink.records), 2, "Sink records should be equal to 2")
        self.assertIsInstance(
            sink.records[-1],
            logging.LogRecord,
            "Last sink record should be an instance of logging.LogRecord",
        )

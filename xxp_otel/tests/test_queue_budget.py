# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from ..telemetry import circuit as circuit_module
from ..telemetry.circuit import ExportCircuit, GatedExporter, QueueBudget
from .common import TestOTELCOmmon


class TestQueueBudget(TestOTELCOmmon):
    def setUp(self):
        super().setUp()
        self.budget = QueueBudget(100, 3, clock=self.clock)

    def test_take_follows_fifo_order_and_keeps_bytes_until_released(self):
        """Test that take follows FIFO order and keeps bytes until released."""
        self.assertTrue(self.budget.try_acquire(40), "Try acquire should return True")
        self.assertTrue(self.budget.try_acquire(30), "Try acquire should return True")
        self.assertEqual(
            self.budget.queued_bytes, 70, "Queued bytes should be equal to 70"
        )

        self.assertEqual(self.budget.take(1), [40], "Take should return [40]")
        self.assertEqual(
            self.budget.queued_items, 1, "Queued items should be equal to 1"
        )
        self.assertEqual(
            self.budget.queued_bytes, 70, "Queued bytes should be equal to 70"
        )

        self.budget.release_bytes(40)
        self.assertEqual(
            self.budget.queued_bytes, 30, "Queued bytes should be equal to 30"
        )

    def test_drops_when_bytes_are_exhausted(self):
        """Test that drops when bytes are exhausted."""
        self.assertTrue(self.budget.try_acquire(80), "Try acquire should return True")
        self.assertFalse(self.budget.try_acquire(30), "Try acquire should return False")
        self.assertTrue(self.budget.try_acquire(20), "Try acquire should return True")
        self.assertEqual(
            self.budget.queued_bytes, 100, "Queued bytes should be equal to 100"
        )

    def test_drops_when_items_are_exhausted(self):
        """Test that drops when items are exhausted."""
        for _index in range(3):
            self.assertTrue(
                self.budget.try_acquire(1), "Try acquire should return True"
            )
        self.assertFalse(self.budget.try_acquire(1), "Try acquire should return False")

    def test_oversized_record_is_admitted_into_an_empty_queue(self):
        """Test that oversized record is admitted into an empty queue."""
        self.assertTrue(self.budget.try_acquire(1000), "Try acquire should return True")
        self.assertFalse(self.budget.try_acquire(1), "Try acquire should return False")

    def test_release_never_goes_below_zero(self):
        """Test that release never goes below zero."""
        self.budget.try_acquire(10)
        self.assertEqual(self.budget.take(5), [10], "Take should return [10]")
        self.budget.release_bytes(50)
        self.assertEqual(
            self.budget.queued_bytes, 0, "Queued bytes should be equal to 0"
        )
        self.assertEqual(
            self.budget.queued_items, 0, "Queued items should be equal to 0"
        )

    def test_after_fork_resets_the_counters(self):
        """Test that after fork resets the counters."""
        self.budget.try_acquire(90)
        self.budget.after_fork()
        self.assertEqual(
            self.budget.queued_bytes, 0, "Queued bytes should be equal to 0"
        )
        self.assertTrue(self.budget.try_acquire(90), "Try acquire should return True")

    def test_drops_are_reported_once_per_minute(self):
        """Test that drops are reported once per minute."""
        self.budget.try_acquire(100)
        self.budget.try_acquire(1)
        with self.assertLogs(circuit_module.__name__, level="WARNING") as logs:
            self.budget.report_drops()
        self.assertIn(
            "dropped 1 new records",
            logs.output[0],
            "Logs should contain 'dropped 1 new records'",
        )

        self.budget.try_acquire(1)
        with self.assertNoLogs(circuit_module.__name__, level="WARNING"):
            self.budget.report_drops()

        self.clock.now = 60
        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            self.budget.report_drops()

    def test_gated_exporter_releases_exported_batches(self):
        """Test that gated exporter releases exported batches."""

        class _Exporter:
            def export(self, batch):
                return "ok"

        self.budget.try_acquire(10)
        self.budget.try_acquire(20)
        gated = GatedExporter(
            _Exporter(),
            ExportCircuit(30, clock=self.clock),
            success="ok",
            failure="dropped",
            queue_budget=self.budget,
        )

        self.assertEqual(gated.export(["a", "b"]), "ok", "Export should return 'ok'")
        self.assertEqual(
            self.budget.queued_bytes, 0, "Queued bytes should be equal to 0"
        )

    def test_batch_in_flight_stays_in_the_budget(self):
        """Test that batch in flight stays in the budget."""
        budget = self.budget
        observed = []

        class _Exporter:
            def export(self, batch):
                observed.append(budget.queued_bytes)
                observed.append(budget.try_acquire(50))
                raise RuntimeError("collector")

        budget.try_acquire(60)
        gated = GatedExporter(
            _Exporter(),
            ExportCircuit(30, clock=self.clock),
            success="ok",
            failure="dropped",
            queue_budget=budget,
        )

        with self.assertRaises(RuntimeError), self.assertLogs(
            circuit_module.__name__, level="WARNING"
        ):
            gated.export(["a"])
        self.assertEqual(
            observed, [60, False], "Observed should be equal to [60, False]"
        )
        self.assertEqual(budget.queued_bytes, 0, "Queued bytes should be equal to 0")

    def test_large_batches_are_split_into_bounded_requests(self):
        """Test that large batches are split into bounded requests."""

        class _Exporter:
            def __init__(self):
                self.calls = []

            def export(self, batch):
                self.calls.append(list(batch))
                return "ok"

        budget = QueueBudget(1000, 10, clock=self.clock)
        for size in (40, 40, 40, 10, 90):
            budget.try_acquire(size)
        exporter = _Exporter()
        gated = GatedExporter(
            exporter,
            ExportCircuit(30, clock=self.clock),
            success="ok",
            failure="dropped",
            queue_budget=budget,
            max_request_bytes=100,
        )

        self.assertEqual(
            gated.export(["a", "b", "c", "d", "e"]), "ok", "Export should return 'ok'"
        )
        self.assertEqual(
            exporter.calls,
            [["a", "b"], ["c", "d"], ["e"]],
            "Calls should be equal to [['a', 'b'], ['c', 'd'], ['e']]",
        )

    def test_failed_chunk_stops_network_for_the_rest(self):
        """Test that failed chunk stops network for the rest."""

        class _Exporter:
            calls = 0

            def export(self, batch):
                _Exporter.calls += 1
                return "no"

        budget = QueueBudget(1000, 10, clock=self.clock)
        for _index in range(3):
            budget.try_acquire(60)
        gated = GatedExporter(
            _Exporter(),
            ExportCircuit(30, clock=self.clock),
            success="ok",
            failure="dropped",
            queue_budget=budget,
            max_request_bytes=100,
        )

        with self.assertLogs(circuit_module.__name__, level="WARNING"):
            self.assertEqual(
                gated.export(["a", "b", "c"]),
                "dropped",
                "Export should return 'dropped'",
            )
        self.assertEqual(_Exporter.calls, 1, "Calls should be equal to 1")

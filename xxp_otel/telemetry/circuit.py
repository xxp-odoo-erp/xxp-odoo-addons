# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import collections
import contextvars
import logging
import threading
import time

_logger = logging.getLogger(__name__)

EXPORT_PAUSE_SECONDS = 30
_PROBE_ADMISSIONS = 1
_DROP_REPORT_SECONDS = 60
_UNKNOWN_RECORD_SIZE = 1024

# Size of the record being emitted, set by the handler for the processor that
# runs synchronously inside the same ``emit`` call.
pending_record_size = contextvars.ContextVar(
    "xxp_otel_pending_record_size", default=_UNKNOWN_RECORD_SIZE
)


class ExportCircuit:
    """Pause export after the collector rejects a batch.

    A health check is the wrong signal: ``/healthz`` can succeed while
    ingestion fails, and it does not drain a queue that is already full.
    The export result is the signal. While the circuit is open, callers drop
    new records and the batch worker fails queued batches without a network
    call. When the pause ends, one admitted record and one export probe the
    collector. Success closes the circuit.
    """

    def __init__(self, retry_after, clock=None, signal="logs"):
        self._retry_after = retry_after
        self._clock = clock or time.monotonic
        self._signal = signal
        self._lock = threading.Lock()
        self._closed = True
        self._retry_at = 0.0
        self._admitted = 0
        self._probe_sent = False
        self._drain_at = float("inf")

    def may_accept(self):
        """Like :meth:`accepting`, without consuming the probe admission."""
        with self._lock:
            if self._closed:
                return True
            return (
                self._clock() >= self._retry_at and self._admitted < _PROBE_ADMISSIONS
            )

    def accepting(self):
        """Return whether one more record may be queued."""
        with self._lock:
            if self._closed:
                return True
            if self._clock() < self._retry_at:
                return False
            if self._admitted >= _PROBE_ADMISSIONS:
                return False
            self._admitted += 1
            return True

    def allow_export(self):
        """Return whether this batch may be sent on the network."""
        with self._lock:
            if self._clock() >= self._drain_at:
                return False
            if self._closed:
                return True
            if self._clock() < self._retry_at or self._probe_sent:
                return False
            self._probe_sent = True
            return True

    def note_success(self):
        with self._lock:
            resumed = not self._closed
            self._reset_closed()
        if resumed:
            _logger.info("OpenTelemetry %s export resumed", self._signal)

    def note_failure(self):
        with self._lock:
            opened = self._closed
            self._closed = False
            self._retry_at = self._clock() + self._retry_after
            self._admitted = 0
            self._probe_sent = False
        if opened:
            _logger.warning(
                "OpenTelemetry %s export paused for %.0f seconds "
                "after the collector stopped accepting data",
                self._signal,
                self._retry_after,
            )

    def drain(self, grace_seconds):
        """Stop network export ``grace_seconds`` from now; used at process exit."""
        with self._lock:
            self._drain_at = min(self._drain_at, self._clock() + grace_seconds)

    def after_fork(self):
        self._lock = threading.Lock()
        self._drain_at = float("inf")
        self._reset_closed()

    def _reset_closed(self):
        self._closed = True
        self._admitted = 0
        self._probe_sent = False


class QueueBudget:
    """Bound the records and characters held by one batch processor.

    The SDK queue is bounded by count only and silently evicts the oldest
    record when full. Admission here rejects the newest record first, so the
    SDK never evicts and the FIFO of sizes stays aligned with its queue.

    Bytes cover the queue and the batch being exported: the exporter keeps a
    whole batch alive until its export returns, which can take the full OTLP
    timeout while the collector hangs.
    """

    def __init__(self, max_bytes, max_items, signal="logs", clock=None):
        self._max_bytes = max_bytes
        self._max_items = max_items
        self._signal = signal
        self._clock = clock or time.monotonic
        self._reset()

    def _reset(self):
        self._lock = threading.Lock()
        self._sizes = collections.deque()
        self._bytes = 0
        self._dropped = 0
        self._reported_at = None

    @property
    def queued_bytes(self):
        return self._bytes

    @property
    def queued_items(self):
        return len(self._sizes)

    def try_acquire(self, size):
        with self._lock:
            sizes = self._sizes
            # A record larger than the whole budget is still admitted when
            # nothing else is held, so one oversized event is never starved.
            if self._bytes and (
                len(sizes) >= self._max_items or self._bytes + size > self._max_bytes
            ):
                self._dropped += 1
                return False
            sizes.append(size)
            self._bytes += size
            return True

    def take(self, count):
        """Return sizes of the ``count`` oldest records leaving the queue.

        Their bytes stay acquired until :meth:`release_bytes`.
        """
        with self._lock:
            sizes = self._sizes
            return [sizes.popleft() for _index in range(min(count, len(sizes)))]

    def release_bytes(self, size):
        with self._lock:
            self._bytes = max(0, self._bytes - size)

    def after_fork(self):
        self._reset()

    def report_drops(self):
        """Log dropped records at most once per minute.

        Called from the export thread: logging from ``emit`` would re-enter
        the telemetry handler.
        """
        with self._lock:
            now = self._clock()
            if not self._dropped or (
                self._reported_at is not None
                and now - self._reported_at < _DROP_REPORT_SECONDS
            ):
                return
            dropped = self._dropped
            self._dropped = 0
            self._reported_at = now
        _logger.warning(
            "OpenTelemetry %s queue is full (%d records or %d bytes); "
            "dropped %d new records",
            self._signal,
            self._max_items,
            self._max_bytes,
            dropped,
        )


class GatedExporter:
    """Skip network export while :class:`ExportCircuit` is open.

    With a :class:`QueueBudget`, a batch is also split into requests of at
    most ``max_request_bytes``: the SDK batches by count, and a batch of large
    records would be serialized into one huge request in memory.
    """

    def __init__(
        self,
        exporter,
        circuit,
        success,
        failure,
        queue_budget=None,
        max_request_bytes=None,
    ):
        self._exporter = exporter
        self._circuit = circuit
        self._success = success
        self._failure = failure
        self._queue_budget = queue_budget
        self._max_request_bytes = max_request_bytes

    def export(self, batch):
        budget = self._queue_budget
        if budget is None:
            return self._export(batch)
        # The batch has already left the processor queue.
        sizes = budget.take(len(batch))
        try:
            budget.report_drops()
            result = self._success
            for chunk in _split_batch(batch, sizes, self._max_request_bytes):
                if self._export(chunk) != self._success:
                    result = self._failure
            return result
        finally:
            budget.release_bytes(sum(sizes))

    def _export(self, batch):
        if not self._circuit.allow_export():
            return self._failure
        try:
            result = self._exporter.export(batch)
        except Exception:
            self._circuit.note_failure()
            raise
        if result == self._success:
            self._circuit.note_success()
        else:
            self._circuit.note_failure()
        return result

    def shutdown(self):
        return self._exporter.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._exporter.force_flush(timeout_millis)


def _split_batch(batch, sizes, max_bytes):
    if not max_bytes:
        return [batch]
    chunks = []
    chunk = []
    chunk_bytes = 0
    for index, item in enumerate(batch):
        size = sizes[index] if index < len(sizes) else _UNKNOWN_RECORD_SIZE
        if chunk and chunk_bytes + size > max_bytes:
            chunks.append(chunk)
            chunk = []
            chunk_bytes = 0
        chunk.append(item)
        chunk_bytes += size
    if chunk:
        chunks.append(chunk)
    return chunks

# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging
import time

from opentelemetry.sdk._logs.export import LogRecordExportResult

from odoo.service import server as odoo_server
from odoo.tests import BaseCase

from ..telemetry.config import Settings


class _SlowExporter:
    """A slow exporter for testing."""

    def __init__(self, delay):
        """Initialize the slow exporter with the given delay.

        Args:
            delay (float): The delay in seconds
        """
        self.delay = delay
        self.calls = 0

    def export(self, batch):
        """Export the given batch of log records.

        Args:
            batch (list): The batch of log records to export

        Returns:
            LogRecordExportResult: The result of the export
        """
        self.calls += 1
        time.sleep(self.delay)
        return LogRecordExportResult.SUCCESS

    def shutdown(self):
        """Shutdown the slow exporter."""
        return None

    def force_flush(self, timeout_millis=30000):
        """Force the slow exporter to flush the log records."""
        return True


class _Clock:
    """A clock for testing."""

    def __init__(self):
        """Initialize the clock with the current time."""
        self.now = 0.0

    def __call__(self):
        """Return the current time."""
        return self.now


class _Exporter:
    """An exporter for testing."""

    def __init__(self):
        """
        Initialize the exporter with the given calls,
        result, error, and shutdowns.
        """
        self.calls = []
        self.result = "ok"
        self.error = None
        self.shutdowns = 0

    def export(self, batch):
        """Export the given batch of log records.

        Args:
            batch (list): The batch of log records to export

        Returns:
            LogRecordExportResult: The result of the export
        """
        self.calls.append(list(batch))
        if self.error is not None:
            raise self.error
        return self.result

    def shutdown(self):
        """Shutdown the exporter."""
        self.shutdowns += 1

    def force_flush(self, timeout_millis=30000):
        """Force the exporter to flush the log records."""
        return True


class _Sink:
    """A sink for testing."""

    def __init__(self):
        """Initialize the sink with the given records."""
        self.records = []

    def emit(self, record):
        """Emit the given log record."""
        self.records.append(record)

    def close(self):
        """Close the sink."""
        return None


class TestOTELCOmmon(BaseCase):
    def setUp(self):
        """Set up the test environment."""
        super().setUp()
        self.clock = self._clock()
        self.exporter = self._exporter()
        self.sink = self._sink()

    def _prefork_server(self, pid):
        """Create a new prefork server with the given PID.

        Args:
            pid (int): The PID of the prefork server

        Returns:
            odoo_server.PreforkServer: The new prefork server
        """
        server = odoo_server.PreforkServer.__new__(odoo_server.PreforkServer)
        server.pid = pid
        return server

    def _slow_exporter(self, delay):
        """Create a new slow exporter with the given delay.

        Args:
            delay (float): The delay in seconds

        Returns:
            _SlowExporter: The new slow exporter
        """
        return _SlowExporter(delay)

    def _clock(self):
        """Create a new clock."""
        return _Clock()

    def _exporter(self):
        """Create a new exporter."""
        return _Exporter()

    def _sink(self):
        """Create a new sink."""
        return _Sink()

    def _record(
        self, msg="message", exc_info=None, name="test", level=logging.INFO, **extra
    ):
        """Create a logging record with the given message and optional extra fields.

        Args:
            msg (str): The message to log
            exc_info (tuple): The exception info
            **extra (dict): Additional fields to add to the record

        Returns:
            logging.LogRecord: The created record
        """
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )
        record.__dict__.update(extra)
        return record

    @staticmethod
    def build_settings(**overrides):
        """Build a new settings object with the given overrides.

        Args:
            **overrides (dict): Keyword arguments to override the default settings
        """
        return Settings(**overrides)

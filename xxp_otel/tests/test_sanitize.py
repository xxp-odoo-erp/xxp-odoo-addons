# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import dataclasses
import json
import logging
import sys

from ..telemetry.sanitize import Capture, Sanitazed
from .common import TestOTELCOmmon


class TestSanitize(TestOTELCOmmon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create a settings object with the given parameters
        cls.settings = cls.build_settings(
            enabled=True,
            trace_http=True,
            trace_rpc=True,
            service_name="odoo-test",
            log_level=logging.INFO,
            log_prefixes=(),
            max_message_length=10,
            max_attribute_length=10,
            max_collection_items=10,
            redact_keys=("token", "password", "authorization"),
        )
        # Create a large settings object with the given parameters
        cls.large = dataclasses.replace(
            cls.settings,
            max_message_length=4096,
            max_attribute_length=1024,
            max_collection_items=100000,
            max_event_bytes=256 * 1024,
        )

    def test_secret_fields_are_redacted_without_mutating_original(self):
        """Test that secret fields are redacted without mutating the original record."""
        record = self._record(
            request_payload={
                "token": "secret-value",
                "nested": {"password": "secret-password"},
            }
        )

        sanitized = Sanitazed.log_record(record, self.settings)

        self.assertEqual(
            sanitized.request_payload["token"], "***", "The token should be redacted"
        )
        self.assertEqual(
            sanitized.request_payload["nested"]["password"],
            "***",
            "The password should be redacted",
        )
        self.assertEqual(
            record.request_payload["token"],  # type: ignore
            "secret-value",
            "The token should not be mutated",
        )

    def test_message_is_truncated(self):
        """Test that the message is truncated."""
        sanitized = Sanitazed.log_record(self._record("123456789012345"), self.settings)
        self.assertTrue(
            sanitized.msg.startswith("1234567890"),
            "Sanitized message should start with '1234567890'",
        )
        self.assertIn(
            "truncated", sanitized.msg, "Sanitized message should contain 'truncated'"
        )

    def test_depth_is_limited(self):
        """Test that the depth is limited."""
        settings = dataclasses.replace(self.settings, max_depth=2)
        value = {"a": {"b": {"c": 1}}}
        self.assertEqual(
            Sanitazed.value("payload", value, settings=settings),
            {"a": {"b": "<max-depth>"}},
            "Sanitized value should be {'a': {'b': '<max-depth>'}}",
        )

    def test_utf8_bytes_are_exported_as_text(self):
        """Test that UTF-8 bytes are exported as text."""
        self.assertEqual(
            Sanitazed.value("body", b"hello", settings=self.large),
            "hello",
            "Sanitized value should be 'hello'",
        )
        self.assertEqual(
            Sanitazed.value("body", b"\xff\xfe\x00", settings=self.large),
            "<bytes:3>",
            "Sanitized value should be '<bytes:3>'",
        )

    def test_bytes_cut_inside_a_character_stay_text(self):
        """
        Test that bytes cut inside a character stay as text.
        """
        self.assertEqual(
            Sanitazed.value("body", b"abc", settings=self.settings),
            "abc",
            "Sanitized value should be 'abc'",
        )
        # The slice length (attribute limit plus the redact overlap) is odd,
        # so it falls inside a 2-byte character. The export stays text.
        settings = dataclasses.replace(self.settings, max_attribute_length=11)
        value = Sanitazed.value("body", ("а" * 400).encode(), settings=settings)
        self.assertNotIn(
            "<bytes:", value, "Sanitized value should not contain '<bytes:'"
        )  # type: ignore
        self.assertIn(
            "<truncated:", value, "Sanitized value should contain '<truncated:'"
        )  # type: ignore
        self.assertIsInstance(
            value.encode("utf-8"), bytes, "Sanitized value should be a bytes object"
        )  # type: ignore

    def test_capture_renders_bounded_json_with_redaction(self):
        """Test that capture renders bounded JSON with redaction."""
        payload = {"access_token": "secret", "items": ["x" * 1000] * 1000}
        rendered = Capture("result", payload).render(self.large, 64 * 1024)

        self.assertLessEqual(
            len(rendered.encode()),
            64 * 1024,
            "Rendered length should be less than 64 * 1024",
        )
        decoded = json.loads(rendered)
        self.assertEqual(
            decoded["result"]["access_token"], "***", "Access token should be redacted"
        )
        items = decoded["result"]["items"]
        self.assertEqual(
            items[-1],
            "<truncated:%d>" % (1000 - len(items) + 1),
            "Last item should be truncated",
        )

    def test_capture_keeps_payload_within_budget_whole(self):
        """Test that capture keeps payload within budget whole."""
        body = "y" * (100 * 1024)
        rendered = Capture("result", {"body": body}).render(self.large, 256 * 1024)
        self.assertEqual(
            json.loads(rendered)["result"]["body"],
            body,
            "Body should be equal to the original",
        )

    def test_capture_keeps_large_collections_within_budget(self):
        """Test that capture keeps large collections within budget."""
        settings = dataclasses.replace(self.large, max_collection_items=100)
        rows = [{"number": "DOCS-%08d" % i, "status": "DELIVERED"} for i in range(2000)]
        rendered = Capture("result", {"entity": rows}).render(settings, 256 * 1024)
        self.assertEqual(
            json.loads(rendered)["result"]["entity"],
            rows,
            "Entity should be equal to the original",
        )

    def test_wide_strings_are_accounted_in_memory_size(self):
        """Test that wide strings are accounted in memory size."""
        latin = self._record(**{"odoo.capture": Capture("result", "x" * 100000)})  # type: ignore
        cyrillic = self._record(**{"odoo.capture": Capture("result", "ж" * 100000)})  # type: ignore

        _sanitized, latin_size = Sanitazed.log_record_with_size(latin, self.large)
        _sanitized, cyrillic_size = Sanitazed.log_record_with_size(cyrillic, self.large)

        self.assertGreater(
            cyrillic_size,
            latin_size + 90000,
            "Cyrillic size should be greater than latin size + 90000",
        )

    def test_capture_is_rendered_once_per_limit(self):
        """Test that capture is rendered once per limit."""
        calls = []

        def factory():
            calls.append(1)
            return {"a": 1}

        capture = Capture("arguments", factory=factory)
        first = capture.render(self.large, 1000)
        self.assertIs(
            capture.render(self.large, 1000),
            first,
            "Capture should be rendered once per limit",
        )
        self.assertEqual(len(calls), 1, "Calls should be equal to 1")
        self.assertEqual(
            repr(capture),
            "<odoo.capture>",
            "Capture should be represented as '<odoo.capture>'",
        )

    def test_record_size_is_bounded_by_event_budget(self):
        """Test that record size is bounded by event budget."""
        response = {"rows": [{"id": i, "name": "n" * 200} for i in range(10000)]}
        record = self._record(**{"odoo.capture": Capture("result", response)})  # type: ignore

        sanitized, size = Sanitazed.log_record_with_size(record, self.large)

        self.assertIsInstance(
            sanitized.__dict__["odoo.capture"],
            str,
            "Sanitized capture should be a string",
        )
        self.assertLessEqual(
            len(sanitized.__dict__["odoo.capture"]),
            256 * 1024,
            "Sanitized capture length should be less than 256 * 1024",
        )
        self.assertLessEqual(
            size, 256 * 1024 + 64, "Size should be less than 256 * 1024 + 64"
        )
        json.loads(sanitized.__dict__["odoo.capture"])

    def test_exception_is_bounded(self):
        """Test that exception is bounded."""
        try:
            raise ValueError("z" * 100000)
        except ValueError:
            record = self._record(exc_info=sys.exc_info())

        sanitized = Sanitazed.log_record(record, self.large)

        self.assertIsNone(sanitized.exc_info, "Sanitized exception info should be None")
        self.assertIsNotNone(
            record.exc_info, "Record exception info should not be None"
        )
        self.assertEqual(
            sanitized.__dict__["exception.type"],
            "ValueError",
            "Sanitized exception type should be 'ValueError'",
        )
        self.assertLessEqual(
            len(sanitized.__dict__["exception.message"]),
            1100,
            "Sanitized exception message length should be less than 1100",
        )
        self.assertLessEqual(
            len(sanitized.__dict__["exception.stacktrace"]),
            4200,
            "Sanitized exception stacktrace length should be less than 4200",
        )

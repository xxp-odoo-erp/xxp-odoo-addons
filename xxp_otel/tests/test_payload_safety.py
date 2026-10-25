# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import dataclasses
import json
import logging
import sys
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from odoo.tests.common import BaseCase

from ..models.ir_http import encode_request_params
from ..telemetry.config import Settings
from ..telemetry.decorators import observe_method
from ..telemetry.runtime import runtime
from ..telemetry.sanitize import (
    _RESERVED_LOG_RECORD_FIELDS,
    Capture,
    Sanitazed,
    record_span_exception,
)

LIMIT = 262144
SECRET = "S3CR3T-value-0123456789abcdef"
SETTINGS = Settings(
    enabled=True,
    trace_http=True,
    trace_rpc=True,
    service_name="odoo-test",
    log_level=logging.INFO,
    log_prefixes=(),
    max_message_length=32768,
    max_attribute_length=32768,
    max_collection_items=100,
    redact_keys=(
        "authorization",
        "cookie",
        "password",
        "token",
        "access_token",
        "api_key",
        "secret",
        "session_id",
    ),
    max_event_bytes=LIMIT,
)


def _record(msg="hello", exc_info=None, **extra):
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, (), exc_info)
    record.__dict__.update(extra)
    return record


def _rows(size, cyrillic=False):
    """Return an API-like response whose compact JSON takes ``size`` bytes."""
    name = "Иванов Иван, г. Москва 😀 漢字" if cyrillic else "John Smith, New York"
    rows = []
    total = 0
    while total < size:
        row = {"id": len(rows), "number": "DOCS-%08d" % len(rows), "name": name}
        total += len(json.dumps(row, ensure_ascii=False).encode()) + 1
        rows.append(row)
    return {"access_token": SECRET, "entity": rows}


def _render(value, limit=LIMIT, settings=SETTINGS):
    capture = Capture("result", value)
    rendered = capture.render(settings, limit)
    return capture, rendered


class TestJsonValidityAndSize(BaseCase):
    def assertValidCapture(self, capture, rendered, limit=LIMIT):
        size = len(rendered.encode("utf-8"))
        self.assertLessEqual(size, limit)
        self.assertEqual(capture.size, size)
        return json.loads(rendered)

    def test_unicode_payload_fits_whole(self):
        payload = {"name": "Привет, мир 😀 漢字", "items": ["ё", "€", "\u00e9"]}
        capture, rendered = _render(payload)
        self.assertEqual(self.assertValidCapture(capture, rendered)["result"], payload)
        self.assertFalse(capture.truncated)

    def test_unicode_payload_is_cut_by_utf8_bytes(self):
        payload = {"text": "ж😀漢" * 100000, "rows": ["щ" * 100] * 1000}
        for limit in (1024, 4096, 65536, LIMIT):
            capture, rendered = _render(payload, limit)
            decoded = self.assertValidCapture(capture, rendered, limit)
            self.assertTrue(capture.truncated)
            self.assertIn("<truncated:", decoded["result"]["text"])

    def test_api_responses_10k_100k_1m(self):
        for size in (10 * 1024, 100 * 1024, 1024 * 1024):
            for cyrillic in (False, True):
                data = _rows(size, cyrillic)
                text = json.dumps(data, ensure_ascii=False)
                expected = dict(data, access_token="***")
                for value in (data, text, text.encode()):
                    with self.subTest(size=size, cyrillic=cyrillic, type=type(value)):
                        capture, rendered = _render(value)
                        decoded = self.assertValidCapture(capture, rendered)
                        self.assertNotIn(SECRET, rendered)
                        result = decoded["result"]
                        if isinstance(value, dict):
                            body = result
                        else:
                            self.assertIsInstance(result, str)
                            body = json.loads(result)
                        if size < LIMIT // 2:
                            self.assertFalse(capture.truncated)
                            self.assertEqual(body, expected)
                            continue
                        self.assertTrue(capture.truncated)
                        self.assertEqual(body["access_token"], "***")
                        self.assertTrue(body["entity"][-1].startswith("<truncated:"))
                        if isinstance(value, dict):
                            self.assertIsNone(capture.original_size)
                        else:
                            self.assertEqual(capture.original_size, len(text.encode()))

    def test_control_characters_and_escapes(self):
        value = '\t\r\n\x00\x01\x1f"\\/' * 60000
        capture, rendered = _render(value)
        decoded = self.assertValidCapture(capture, rendered)
        self.assertTrue(decoded["result"].startswith('\t\r\n\x00\x01\x1f"\\/'))
        self.assertGreater(capture.size, LIMIT - 1024)

    def test_non_finite_floats_are_valid_json(self):
        _capture, rendered = _render([float("nan"), float("inf"), 1.5])

        def reject(constant):
            raise ValueError(constant)

        decoded = json.loads(rendered, parse_constant=reject)
        self.assertEqual(decoded["result"], ["nan", "inf", 1.5])

    def test_lone_surrogates_do_not_break_export(self):
        _capture, rendered = _render({"text": "a\ud800b", "json": '{"k": "\\udc00"}'})
        rendered.encode("utf-8")
        json.loads(rendered)

    def test_nested_structures_are_cut_at_max_depth(self):
        value = current = {}
        for _index in range(50):
            current["child"] = current = {}
        capture, rendered = _render(value)
        decoded = self.assertValidCapture(capture, rendered)
        self.assertTrue(capture.truncated)
        self.assertIn("<max-depth>", rendered)
        self.assertIn("child", decoded["result"])

    def test_large_collections_keep_counts(self):
        numbers = list(range(1000000))
        capture, rendered = _render(numbers)
        kept = self.assertValidCapture(capture, rendered)["result"]
        self.assertEqual(kept[-1], "<truncated:%d>" % (1000000 - len(kept) + 1))
        self.assertEqual(kept[:-1], numbers[: len(kept) - 1])

        mapping = {"k%d" % index: index for index in range(200000)}
        capture, rendered = _render(mapping)
        kept = self.assertValidCapture(capture, rendered)["result"]
        self.assertTrue(kept["_truncated"])
        self.assertEqual(kept["_omitted"], 200000 - len(kept) + 2)
        self.assertEqual(kept["k0"], 0)

    def test_request_params_stay_valid_json(self):
        params = {"args": ["ж" * 30000], "password": "x"}
        encoded = encode_request_params(params, SETTINGS)
        self.assertLessEqual(len(encoded.encode()), SETTINGS.max_attribute_length)
        self.assertEqual(json.loads(encoded)["password"], "***")

    def test_event_size_is_bounded_in_utf8(self):
        try:
            raise ValueError("ы" * 100000)
        except ValueError:
            exc_info = sys.exc_info()
        record = _record(
            "ж" * 40000,
            exc_info=exc_info,
            otel_event="integration.response",
            request_payload={"body": "щ" * 50000, "rows": ["ё" * 100] * 1000},
            **{"odoo.capture": Capture("result", _rows(1024 * 1024, True))},
        )

        cloned, _size = Sanitazed.log_record_with_size(record, SETTINGS)

        total = 0
        for key, value in cloned.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS and key != "msg":
                continue
            if isinstance(value, str):
                total += len(value.encode("utf-8"))
            elif isinstance(value, dict | list):
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                total += len(encoded.encode())
        self.assertLessEqual(total, LIMIT)
        self.assertGreater(total, LIMIT // 2)
        json.loads(cloned.__dict__["odoo.capture"])
        self.assertIs(cloned.__dict__["odoo.capture.truncated"], True)

    def test_capture_metadata_for_cut_text_payload(self):
        body = "x" * (1024 * 1024)
        record = _record(**{"odoo.capture": Capture("result", body)})

        cloned = Sanitazed.log_record(record, SETTINGS)

        self.assertIs(cloned.__dict__["odoo.capture.truncated"], True)
        self.assertEqual(cloned.__dict__["odoo.capture.original_size"], len(body))
        small = Sanitazed.log_record(
            _record(**{"odoo.capture": Capture("result", "ok")}), SETTINGS
        )
        self.assertNotIn("odoo.capture.truncated", small.__dict__)


class TestSecretsInStrings(BaseCase):
    def assertNoSecret(self, value, settings=SETTINGS, limit=LIMIT):
        _capture, rendered = _render(value, limit, settings)
        self.assertNotIn(SECRET, rendered)
        return json.loads(rendered)["result"]

    def test_json_string_is_sanitized_by_keys(self):
        body = json.dumps(
            {
                "access_token": SECRET,
                "user": {"login": "admin", "Password": SECRET},
                "items": [{"api-key": SECRET, "name": "Товар"}],
            }
        )
        result = self.assertNoSecret({"body": body})
        inner = json.loads(result["body"])
        self.assertEqual(inner["access_token"], "***")
        self.assertEqual(inner["user"], {"login": "admin", "Password": "***"})
        self.assertEqual(inner["items"][0], {"api-key": "***", "name": "Товар"})

    def test_nested_json_string_and_bytes(self):
        nested = json.dumps({"token": SECRET})
        body = json.dumps({"payload": nested, "ok": True})
        self.assertNoSecret({"body": body})
        self.assertNoSecret({"body": body.encode()})
        self.assertNoSecret(bytearray(body.encode()))
        self.assertNoSecret("  \n" + body)

    def test_json_string_with_ascii_escapes_is_compacted(self):
        body = json.dumps({"name": "Иванов", "secret": SECRET}, ensure_ascii=True)
        result = self.assertNoSecret(body)
        self.assertEqual(json.loads(result), {"name": "Иванов", "secret": "***"})

    def test_invalid_or_oversized_json_falls_back_to_rules(self):
        broken = '{"password": "%s", "rows": [' % SECRET
        self.assertNoSecret(broken)
        small = dataclasses.replace(SETTINGS, max_event_bytes=4096)
        big = json.dumps({"access_token": SECRET, "rows": ["x" * 100] * 1000})
        self.assertNoSecret(big, small, 4096)
        escaped = json.dumps(json.dumps({"token": SECRET}))
        self.assertNoSecret("payload=" + escaped)

    def test_plain_text_rules(self):
        texts = (
            "user=admin&password=%s&lang=ru" % SECRET,
            "GET /api\nAuthorization: Bearer %s\nAccept: */*" % SECRET,
            "Authorization: Basic %s" % SECRET,
            "callback https://admin:%s@example.com/path" % SECRET,
            "error {'client_secret': '%s', 'id': 7}" % SECRET,
            "call(token=%s, partner_id=3)" % SECRET,
            "Set-Cookie: session_id=%s; Path=/" % SECRET,
            "X-Api-Key: %s" % SECRET,
        )
        for text in texts:
            with self.subTest(text=text):
                result = self.assertNoSecret(text)
                self.assertIn("***", result)

    def test_jwt_is_masked(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl"
        result = self.assertNoSecret({"note": "issued %s for user" % jwt})
        self.assertNotIn(jwt, result["note"])

    def test_secret_crossing_the_cut_is_masked(self):
        # The cut falls 3 characters into the secret value.
        cut = SETTINGS.max_attribute_length - 32
        text = "x" * (cut - 12) + "password=" + SECRET + " tail" * 100
        record = _record(note=text)
        cloned = Sanitazed.log_record(record, SETTINGS)
        self.assertNotIn(SECRET[:3], cloned.note)
        self.assertIn("<truncated:", cloned.note)

    def test_plain_text_without_secrets_is_unchanged(self):
        text = (
            "Документ DOCS-00000001 обработан: менеджер Иванов, тел. +7 900 000-00-00"
        )
        self.assertEqual(self.assertNoSecret(text), text)

    def test_message_is_redacted(self):
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "External API response %s",
            ('{"access_token": "%s"}' % SECRET,),
            None,
        )
        cloned = Sanitazed.log_record(record, SETTINGS)
        self.assertNotIn(SECRET, cloned.getMessage())
        self.assertIn("External API response", cloned.getMessage())


class _Unprintable(Exception):
    def __str__(self):
        raise RuntimeError("no str")


class TestSecretsInExceptions(BaseCase):
    def _exc_info(self):
        try:
            try:
                raise ValueError(
                    'External API 401: {"access_token": "%s", "detail": "expired"}'
                    % SECRET
                )
            except ValueError as err:
                raise RuntimeError(
                    {"password": SECRET, "url": "https://u:%s@api.example.com" % SECRET}
                ) from err
        except RuntimeError:
            return sys.exc_info()

    def test_log_exception_message_and_stacktrace(self):
        cloned = Sanitazed.log_record(_record(exc_info=self._exc_info()), SETTINGS)

        self.assertIsNone(cloned.exc_info)
        self.assertEqual(cloned.__dict__["exception.type"], "RuntimeError")
        message = cloned.__dict__["exception.message"]
        stacktrace = cloned.__dict__["exception.stacktrace"]
        self.assertNotIn(SECRET, message)
        self.assertNotIn(SECRET, stacktrace)
        self.assertIn("'password': '***'", message)
        self.assertIn("ValueError: External API 401", stacktrace)
        self.assertIn("RuntimeError", stacktrace)

    def test_huge_chained_exception_is_bounded(self):
        try:
            try:
                raise ValueError("token=%s " % SECRET + "ж" * 1000000)
            except ValueError as err:
                raise RuntimeError("я" * 1000000) from err
        except RuntimeError:
            exc_info = sys.exc_info()
        cloned, size = Sanitazed.log_record_with_size(
            _record(exc_info=exc_info), SETTINGS
        )
        stacktrace = cloned.__dict__["exception.stacktrace"]
        self.assertLessEqual(len(stacktrace), SETTINGS.max_message_length + 32)
        self.assertNotIn(SECRET, stacktrace)
        self.assertLess(size, 2 * LIMIT)

    def test_unprintable_exception(self):
        try:
            raise _Unprintable("x")
        except _Unprintable:
            cloned = Sanitazed.log_record(_record(exc_info=sys.exc_info()), SETTINGS)
        self.assertEqual(
            cloned.__dict__["exception.message"], "<unprintable _Unprintable>"
        )


class TestSpanExceptions(BaseCase):
    def setUp(self):
        super().setUp()
        if TracerProvider is None:
            self.skipTest("OpenTelemetry SDK is not installed")
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.addCleanup(self.provider.shutdown)
        for target, name, value in (
            (runtime, "ensure_initialized", True),
            (runtime, "accepts_logs", True),
        ):
            patcher = patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = patch(
            "odoo.addons.xxp_otel.telemetry.decorators.get_settings",
            return_value=SETTINGS,
        )
        settings.start()
        self.addCleanup(settings.stop)

    def assertSanitizedExceptionSpan(self, span):
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertEqual(span.status.description, "ValueError")
        self.assertEqual([event.name for event in span.events], ["exception"])
        attributes = dict(span.events[0].attributes)
        self.assertEqual(attributes["exception.type"], "ValueError")
        for value in attributes.values():
            self.assertNotIn(SECRET, str(value))
        self.assertIn("Bearer ***", attributes["exception.message"])

    def test_observed_method_exports_sanitized_exception_event(self):
        tracer = self.provider.get_tracer(__name__)
        with patch.object(trace, "get_tracer", return_value=tracer):

            @observe_method()
            def failing(token=None):
                raise ValueError(f"401 for Bearer {SECRET} password={SECRET}")

        with self.assertLogs(__name__, level="INFO") as logs:
            with self.assertRaises(ValueError):
                failing(token=SECRET)

        (span,) = self.exporter.get_finished_spans()
        self.assertSanitizedExceptionSpan(span)
        for record in logs.records:
            cloned = Sanitazed.log_record(record, SETTINGS)
            for key, value in cloned.__dict__.items():
                if key.startswith(("exception.", "odoo.capture")) or key == "msg":
                    self.assertNotIn(SECRET, str(value))

    def test_record_span_exception_helper(self):
        tracer = self.provider.get_tracer(__name__)
        with tracer.start_as_current_span(
            "GET /external", record_exception=False, set_status_on_exception=False
        ) as span:
            try:
                raise ValueError("Bearer %s" % SECRET)
            except ValueError as exc:
                record_span_exception(span, exc, SETTINGS)

        (span,) = self.exporter.get_finished_spans()
        self.assertSanitizedExceptionSpan(span)

    def test_record_span_exception_never_raises(self):
        class _BrokenSpan:
            def is_recording(self):
                raise RuntimeError("broken")

        record_span_exception(_BrokenSpan(), ValueError("x"), SETTINGS)

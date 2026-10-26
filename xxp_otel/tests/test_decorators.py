import dataclasses
import inspect
import json
import logging
from unittest.mock import patch

from odoo.tests.common import BaseCase

from ..telemetry.config import Settings
from ..telemetry.decorators import _bind_arguments, _get_odoo_context, observe_method
from ..telemetry.runtime import runtime
from ..telemetry.sanitize import Capture, Sanitazed

_SETTINGS = Settings(
    enabled=True,
    trace_http=True,
    trace_rpc=True,
    service_name="odoo-test",
    log_level=logging.INFO,
    log_prefixes=(),
    max_message_length=4096,
    max_attribute_length=4096,
    max_collection_items=100,
    redact_keys=("token", "password"),
)


class _Company:
    id = 7


class _Env:
    uid = 42
    company = _Company()


class _Recordset:
    _name = "test.model"
    ids = [10, 20]
    env = _Env()

    @observe_method(capture_result=True)
    def observed(self, vals, token=None):
        return {"done": vals}

    @observe_method(event="test.fail")
    def failing(self, vals=None):
        raise ValueError("boom")

    @observe_method(capture_result=True)
    def large(self, size):
        return {"body": "x" * size}


def _exported_capture(record, settings=_SETTINGS):
    sanitized = Sanitazed.log_record(record, settings)
    return json.loads(sanitized.__dict__["odoo.capture"])


class TestDecorators(BaseCase):
    def setUp(self):
        super().setUp()
        settings = patch(
            "odoo.addons.xxp_otel.telemetry.decorators.get_settings",
            return_value=_SETTINGS,
        )
        settings.start()
        self.addCleanup(settings.stop)

    def _enable(self, accepts=True):
        for name, value in (("ensure_initialized", True), ("accepts_logs", accepts)):
            patcher = patch.object(runtime, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_bind_arguments_excludes_self(self):
        def method(self, vals, options=None):
            return True

        receiver = _Recordset()
        vals = {"name": "X"}
        bound = _bind_arguments(
            inspect.signature(method), (receiver, vals), {"options": {"a": 1}}
        )

        self.assertEqual(bound, {"vals": vals, "options": {"a": 1}})

    def test_odoo_context_is_extracted(self):
        context = _get_odoo_context(_Recordset())

        self.assertEqual(context["odoo.model"], "test.model")
        self.assertEqual(context["odoo.record_ids"], [10, 20])
        self.assertEqual(context["odoo.record_count"], 2)
        self.assertEqual(context["odoo.uid"], 42)
        self.assertEqual(context["odoo.company_id"], 7)

    def test_odoo_context_limits_ids_of_large_recordsets(self):
        receiver = _Recordset()
        receiver._ids = tuple(range(1, 100001))

        context = _get_odoo_context(receiver, max_ids=5)

        self.assertEqual(context["odoo.record_ids"], [1, 2, 3, 4, 5])
        self.assertEqual(context["odoo.record_count"], 100000)

    def test_disabled_telemetry_calls_method_directly(self):
        with patch.object(runtime, "ensure_initialized", return_value=False):
            self.assertEqual(_Recordset().observed("v"), {"done": "v"})

    def test_call_and_result_are_logged(self):
        self._enable()
        with self.assertLogs(__name__, level="INFO") as logs:
            result = _Recordset().observed({"name": "X"}, token="secret")

        self.assertEqual(result, {"done": {"name": "X"}})
        call, completed = logs.records
        self.assertEqual(call.otel_event, "odoo.method.call")
        self.assertEqual(call.__dict__["odoo.model"], "test.model")
        self.assertIsInstance(call.__dict__["odoo.capture"], Capture)
        self.assertEqual(
            _exported_capture(call),
            {"arguments": {"vals": {"name": "X"}, "token": "***"}},
        )
        self.assertEqual(completed.otel_event, "odoo.method.call.result")
        self.assertEqual(
            _exported_capture(completed), {"result": {"done": {"name": "X"}}}
        )

    def test_decorator_does_not_sanitize_or_copy(self):
        self._enable()
        vals = {"name": "X"}
        with patch.object(Sanitazed, "value", wraps=Sanitazed.value) as value:
            with self.assertLogs(__name__, level="INFO") as logs:
                _Recordset().observed(vals)

        self.assertEqual(value.call_count, 0)
        capture = logs.records[1].__dict__["odoo.capture"]
        self.assertIs(capture._value["done"], vals)

    def test_payload_is_encoded_once_per_record(self):
        self._enable()
        with self.assertLogs(__name__, level="INFO") as logs:
            _Recordset().observed({"name": "X"})

        with patch.object(Sanitazed, "_encode", wraps=Sanitazed._encode) as encode:
            for record in logs.records:
                Sanitazed.log_record(record, _SETTINGS)

        self.assertEqual(encode.call_count, 2)

    def test_no_capture_when_export_is_closed(self):
        self._enable(accepts=False)
        with self.assertLogs(__name__, level="INFO") as logs:
            _Recordset().observed({"name": "X"})

        for record in logs.records:
            self.assertNotIn("odoo.capture", record.__dict__)

    def test_large_result_is_bounded(self):
        self._enable()
        settings = dataclasses.replace(_SETTINGS, max_event_bytes=256 * 1024)
        with self.assertLogs(__name__, level="INFO") as logs:
            _Recordset().large(1024 * 1024)

        rendered = Sanitazed.log_record(logs.records[1], settings).__dict__[
            "odoo.capture"
        ]
        self.assertLessEqual(len(rendered), 256 * 1024)
        self.assertIn("<truncated:", json.loads(rendered)["result"]["body"])

    def test_error_reuses_the_rendered_capture(self):
        self._enable()
        with self.assertLogs(__name__, level="INFO") as logs:
            with self.assertRaises(ValueError):
                _Recordset().failing({"name": "X"})

        call, error = logs.records
        self.assertEqual(
            [call.otel_event, error.otel_event], ["test.fail", "test.fail.error"]
        )
        self.assertIs(error.__dict__["odoo.capture"], call.__dict__["odoo.capture"])
        with patch.object(Sanitazed, "_encode", wraps=Sanitazed._encode) as encode:
            first = Sanitazed.log_record(call, _SETTINGS).__dict__["odoo.capture"]
            second = Sanitazed.log_record(error, _SETTINGS).__dict__["odoo.capture"]

        self.assertEqual(first, second)
        self.assertEqual(encode.call_count, 1)

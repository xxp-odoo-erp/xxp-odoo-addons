# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import dataclasses
import json
import logging
from unittest.mock import patch

from ..models.ir_http import _odoo_request_attributes, encode_request_params
from .common import TestOTELCOmmon


class _Endpoint:
    routing = {"type": "json"}


class _Env:
    uid = None


class _Request:
    def __init__(self, params):
        self.db = "smartpost"
        self.params = params
        self.env = _Env()


class TestEncodeRequestParams(TestOTELCOmmon):
    def setUp(self):
        super().setUp()
        self.settings = self.build_settings(
            enabled=True,
            trace_http=True,
            trace_rpc=True,
            service_name="odoo-test",
            log_level=logging.INFO,
            log_prefixes=(),
            max_message_length=4096,
            max_attribute_length=4096,
            max_collection_items=10,
            redact_keys=("password", "token", "session_id"),
        )

    def test_rpc_arguments_are_kept(self):
        """Test that RPC arguments are kept."""
        encoded = encode_request_params(
            {
                "model": "sale.order",
                "method": "action_confirm",
                "args": [[7], {"name": "Order"}],
                "kwargs": {"context_key": "value"},
            },
            self.settings,
        )
        params = json.loads(encoded)  # type: ignore

        self.assertEqual(
            params["model"], "sale.order", "Model should be equal to 'sale.order'"
        )
        self.assertEqual(
            params["method"],
            "action_confirm",
            "Method should be equal to 'action_confirm'",
        )
        self.assertEqual(
            params["args"],
            [[7], {"name": "Order"}],
            "Args should be equal to [[7], {'name': 'Order'}]",
        )
        self.assertEqual(
            params["kwargs"],
            {"context_key": "value"},
            "Kwargs should be equal to {'context_key': 'value'}",
        )

    def test_secret_keys_are_redacted(self):
        """Test that secret keys are redacted."""
        encoded = encode_request_params(
            {
                "model": "res.users",
                "method": "write",
                "args": [[1], {"name": "Ada", "password": "secret"}],
                "session_id": "sid",
            },
            self.settings,
        )
        params = json.loads(encoded)  # type: ignore

        self.assertEqual(
            params["args"][1]["password"], "***", "Password should be equal to '***'"
        )
        self.assertEqual(
            params["args"][1]["name"], "Ada", "Name should be equal to 'Ada'"
        )
        self.assertEqual(
            params["session_id"], "***", "Session ID should be equal to '***'"
        )

    def test_long_payload_is_truncated(self):
        """Test that long payload is truncated."""
        settings = dataclasses.replace(self.settings, max_attribute_length=32)
        encoded = encode_request_params(
            {"args": ["x" * 200]},
            settings,
        )
        self.assertIsNotNone(encoded, "Encoded should not be None")
        self.assertLessEqual(
            len(encoded or ""),
            32 + len("...<truncated:200>"),
            "Encoded length should be less than or equal to "
            "32 + length of '<truncated:200>'",
        )  # type: ignore
        self.assertIn("<truncated:", encoded)  # type: ignore

    def test_empty_and_non_mapping_are_skipped(self):
        """Test that empty and non-mapping are skipped."""
        settings = self.settings
        self.assertIsNone(encode_request_params({}, settings), "Encoded should be None")
        self.assertIsNone(
            encode_request_params(None, settings), "Encoded should be None"
        )
        self.assertIsNone(
            encode_request_params(["not-a-mapping"], settings), "Encoded should be None"
        )

    def test_params_attribute_follows_the_setting(self):
        """Test that params attribute follows the setting."""
        params = {"model": "sale.order", "method": "write", "args": [[1]]}
        request = _Request(params)

        with patch("odoo.addons.xxp_otel.models.ir_http.request", request):
            captured = _odoo_request_attributes(
                _Endpoint(),
                dataclasses.replace(self.settings, capture_request_params=True),
            )
            skipped = _odoo_request_attributes(
                _Endpoint(),
                dataclasses.replace(self.settings, capture_request_params=False),
            )

        self.assertEqual(
            captured["odoo.model"],
            "sale.order",
            "Model should be equal to 'sale.order'",
        )
        self.assertEqual(
            captured["odoo.method"], "write", "Method should be equal to 'write'"
        )
        self.assertIn(
            '"args":[[1]]',
            captured["odoo.request.params"],
            "Odoo request params should contain 'args':[[1]]",
        )
        self.assertNotIn(
            "odoo.request.params",
            skipped,
            "Odoo request params should not be in skipped",
        )

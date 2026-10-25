# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import dataclasses
import logging

from ..telemetry.config import should_trace_http_route
from .common import TestOTELCOmmon


class TestHttpRouteFilter(TestOTELCOmmon):
    def setUp(self):
        super().setUp()
        self.settings = self.build_settings(
            enabled=True,
            trace_http=True,
            trace_rpc=True,
            service_name="odoo",
            log_level=logging.INFO,
            log_prefixes=(),
            max_message_length=1024,
            max_attribute_length=1024,
            max_collection_items=10,
            redact_keys=(),
        )

    def test_empty_lists_trace_every_route(self):
        """Test that empty lists trace every route."""
        self.assertTrue(
            should_trace_http_route("/websocket", "/websocket", self.settings),
            "Traces websocket route",
        )
        self.assertTrue(
            should_trace_http_route(
                "/web/dataset/call_kw/<string:model>/<string:method>",
                "/web/dataset/call_kw/sale.order/action_confirm",
                self.settings,
            ),
            "Traces dataset route",
        )

    def test_exclude_matches_path_boundary(self):
        """Test that exclude matches path boundary."""
        settings = dataclasses.replace(
            self.settings,
            trace_exclude_routes=("/websocket", "/web/static", "/web/assets"),
        )
        self.assertFalse(
            should_trace_http_route("/websocket", "/websocket", settings),
            "Does not trace websocket route",
        )
        self.assertFalse(
            should_trace_http_route(
                "/web/static/<string:filename>",
                "/web/static/lib/jquery.js",
                settings,
            ),
            "Does not trace static route",
        )
        self.assertTrue(
            should_trace_http_route("/webhook/external", "/webhook/external", settings),
            "Traces webhook route",
        )
        self.assertTrue(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Traces login route",
        )

    def test_allowlist_limits_traced_routes(self):
        """Test that allowlist limits traced routes."""
        settings = dataclasses.replace(self.settings, trace_routes=("/web/dataset",))
        self.assertTrue(
            should_trace_http_route(
                "/web/dataset/call_kw/<string:model>/<string:method>",
                "/web/dataset/call_kw/sale.order/action_confirm",
                settings,
            ),
            "Traces dataset route",
        )
        self.assertFalse(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Does not trace login route",
        )
        self.assertFalse(
            should_trace_http_route("/websocket", "/websocket", settings),
            "Does not trace websocket route",
        )

    def test_patterns_are_normalized(self):
        """Test that patterns are normalized."""
        settings = dataclasses.replace(
            self.settings, trace_exclude_routes=(" web/static/ ",)
        )
        self.assertFalse(
            should_trace_http_route(
                "/web/static/<path:p>", "/web/static/a.js", settings
            ),
            "Does not trace static route",
        )
        self.assertTrue(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Traces login route",
        )

    def test_star_matches_every_route(self):
        """Test that star matches every route."""
        settings = dataclasses.replace(self.settings, trace_exclude_routes=("*",))
        self.assertFalse(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Does not trace login route",
        )

    def test_root_pattern_matches_only_root(self):
        """Test that root pattern matches only root."""
        settings = dataclasses.replace(self.settings, trace_exclude_routes=("/",))
        self.assertFalse(
            should_trace_http_route("/", "/", settings), "Does not trace root route"
        )
        self.assertTrue(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Traces login route",
        )

    def test_exclude_wins_over_allowlist(self):
        """Test that exclude wins over allowlist."""
        settings = dataclasses.replace(
            self.settings,
            trace_routes=("/web",),
            trace_exclude_routes=("/web/static",),
        )
        self.assertTrue(
            should_trace_http_route("/web/login", "/web/login", settings),
            "Traces login route",
        )
        self.assertFalse(
            should_trace_http_route(
                "/web/static/src/js/boot.js", "/web/static/src/js/boot.js", settings
            ),
            "Does not trace static route",
        )

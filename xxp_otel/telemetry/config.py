# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging
from dataclasses import dataclass
from functools import lru_cache

from odoo.tools import config as odoo_config

_DEFAULT_REDACT_KEYS = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "secret",
    "session_id",
    "sessionid",
)
_DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"
_DEFAULT_SAMPLER = "parentbased_traceidratio"
_DEFAULT_SAMPLER_ARG = 0.1
_DEFAULT_TRACE_EXCLUDE_ROUTES = "/websocket,/longpolling"
_DEFAULT_MAX_EVENT_BYTES = 256 * 1024
_DEFAULT_LOG_QUEUE_MAX_BYTES = 32 * 1024 * 1024
_DEFAULT_LOG_MAX_QUEUE_SIZE = 2048
_DEFAULT_LOG_MAX_EXPORT_BATCH_SIZE = 64
_DEFAULT_LOG_SCHEDULE_DELAY_MS = 200


@dataclass(frozen=True)
class Settings:
    enabled: bool
    trace_http: bool
    trace_rpc: bool
    service_name: str
    log_level: int
    log_prefixes: tuple
    max_message_length: int
    max_attribute_length: int
    max_collection_items: int
    redact_keys: tuple
    otlp_endpoint: str = _DEFAULT_OTLP_ENDPOINT
    otlp_traces_endpoint: str = ""
    otlp_logs_endpoint: str = ""
    otlp_headers: tuple = ()
    otlp_timeout: float = 10.0
    traces_sampler: str = _DEFAULT_SAMPLER
    traces_sampler_arg: float = _DEFAULT_SAMPLER_ARG
    trace_routes: tuple = ()
    trace_exclude_routes: tuple = ()
    capture_request_params: bool = False
    log_prefix_level: int = logging.WARNING
    max_depth: int = 6
    max_event_bytes: int = _DEFAULT_MAX_EVENT_BYTES
    log_queue_max_bytes: int = _DEFAULT_LOG_QUEUE_MAX_BYTES
    log_max_queue_size: int = _DEFAULT_LOG_MAX_QUEUE_SIZE
    log_max_export_batch_size: int = _DEFAULT_LOG_MAX_EXPORT_BATCH_SIZE
    log_schedule_delay_ms: int = _DEFAULT_LOG_SCHEDULE_DELAY_MS

    @staticmethod
    def _signal_endpoint(endpoint, path):
        trimmed = (endpoint or _DEFAULT_OTLP_ENDPOINT).strip().rstrip("/")
        suffix = "/" + path
        if trimmed.endswith(suffix):
            return trimmed
        return trimmed + suffix

    def traces_endpoint(self):
        return self._signal_endpoint(
            self.otlp_traces_endpoint or self.otlp_endpoint,
            "v1/traces",
        )

    def logs_endpoint(self):
        return self._signal_endpoint(
            self.otlp_logs_endpoint or self.otlp_endpoint,
            "v1/logs",
        )


class SettingsBuilder:
    """Build :class:`Settings` from the ``[options]`` section of odoo.conf.

    Odoo converts ``true``/``false`` while loading the config file, so values
    may already be booleans; everything else arrives as raw strings.
    """

    def __init__(self, options):
        self.options = options

    def build(self):
        return Settings(
            enabled=self._bool("otel_enabled", False),
            trace_http=self._bool("otel_trace_http", True),
            trace_rpc=self._bool("otel_trace_rpc", True),
            service_name=self._str("otel_service_name", "odoo"),
            log_level=self._log_level("otel_log_level", "INFO"),
            log_prefixes=self._csv("otel_log_prefixes"),
            max_message_length=self._int("otel_max_message_length", 32768, minimum=256),
            max_attribute_length=self._int(
                "otel_max_attribute_length", 32768, minimum=256
            ),
            max_collection_items=self._int("otel_max_collection_items", 100, minimum=1),
            redact_keys=tuple(
                dict.fromkeys(_DEFAULT_REDACT_KEYS + self._csv("otel_redact_keys"))
            ),
            otlp_endpoint=self._str("otel_otlp_endpoint", _DEFAULT_OTLP_ENDPOINT),
            otlp_traces_endpoint=self._str("otel_otlp_traces_endpoint", ""),
            otlp_logs_endpoint=self._str("otel_otlp_logs_endpoint", ""),
            otlp_headers=self._headers("otel_otlp_headers"),
            otlp_timeout=self._float("otel_otlp_timeout", 10.0, minimum=0.1),
            traces_sampler=self._str("otel_traces_sampler", _DEFAULT_SAMPLER).lower(),
            traces_sampler_arg=self._float(
                "otel_traces_sampler_arg",
                _DEFAULT_SAMPLER_ARG,
                minimum=0.0,
                maximum=1.0,
            ),
            trace_routes=self._csv("otel_trace_routes"),
            trace_exclude_routes=self._csv(
                "otel_trace_exclude_routes", _DEFAULT_TRACE_EXCLUDE_ROUTES
            ),
            capture_request_params=self._bool("otel_capture_request_params", False),
            log_prefix_level=self._log_level("otel_log_prefix_level", "WARNING"),
            max_depth=self._int("otel_max_depth", 6, minimum=1),
            max_event_bytes=self._int(
                "otel_max_event_bytes", _DEFAULT_MAX_EVENT_BYTES, minimum=1024
            ),
            log_queue_max_bytes=self._int(
                "otel_log_queue_max_bytes",
                _DEFAULT_LOG_QUEUE_MAX_BYTES,
                minimum=1024 * 1024,
            ),
            log_max_queue_size=self._int(
                "otel_log_max_queue_size", _DEFAULT_LOG_MAX_QUEUE_SIZE, minimum=1
            ),
            log_max_export_batch_size=self._int(
                "otel_log_max_export_batch_size",
                _DEFAULT_LOG_MAX_EXPORT_BATCH_SIZE,
                minimum=1,
            ),
            log_schedule_delay_ms=self._int(
                "otel_log_schedule_delay",
                _DEFAULT_LOG_SCHEDULE_DELAY_MS,
                minimum=50,
            ),
        )

    def _bool(self, name, default):
        value = self.options.get(name)
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _str(self, name, default):
        value = self.options.get(name)
        if value is None:
            return default
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip() or default

    def _int(self, name, default, minimum=0):
        value = self.options.get(name)
        if value is None or value == "":
            return default
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    def _float(self, name, default, minimum=None, maximum=None):
        value = self.options.get(name)
        if value is None or value == "":
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if minimum is not None:
            number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    def _csv(self, name, default=""):
        raw = self._str(name, default)
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    def _headers(self, name):
        pairs = []
        for item in self._csv(name):
            key, separator, value = item.partition("=")
            key = key.strip()
            if separator and key:
                pairs.append((key, value.strip()))
        return tuple(pairs)

    def _log_level(self, name, default):
        level = getattr(logging, self._str(name, default).upper(), None)
        return level if isinstance(level, int) else getattr(logging, default)


@lru_cache(maxsize=1)
def get_settings():
    return SettingsBuilder(odoo_config.options).build()


def should_trace_http_route(route, path, settings):
    """Return whether this HTTP route should create a server span.

    An empty ``trace_routes`` list traces every route. ``trace_exclude_routes``
    always wins. Patterns are path prefixes separated on ``/``, so ``/web``
    matches ``/web/login`` and does not match ``/webhook``.
    """
    candidates = (route, path)
    if _route_matches(candidates, settings.trace_exclude_routes):
        return False
    if not settings.trace_routes:
        return True
    return _route_matches(candidates, settings.trace_routes)


def clear_settings_cache():
    get_settings.cache_clear()


def _route_matches(candidates, patterns):
    if not patterns:
        return False
    match_all, exact, prefixes = _compile_route_patterns(patterns)
    if match_all:
        return True
    return any(
        candidate and (candidate in exact or candidate.startswith(prefixes))
        for candidate in candidates
    )


@lru_cache(maxsize=16)
def _compile_route_patterns(patterns):
    """Return ``(match_all, exact_paths, path_prefixes)`` for ``patterns``."""
    if "*" in patterns:
        return True, frozenset(), ()
    exact = set()
    for pattern in patterns:
        normalized = pattern.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        exact.add(normalized.rstrip("/") or "/")
    # "/" matches only the root path, not every route.
    prefixes = tuple(item + "/" for item in exact if item != "/")
    return False, frozenset(exact), prefixes

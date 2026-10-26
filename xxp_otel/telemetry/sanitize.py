# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

"""Turn arbitrary values into bounded, redacted JSON for telemetry export.

A log record, a captured payload and a span exception share one walk
(:func:`_convert`) under a :class:`Budget` of UTF-8 bytes. Captured payloads
are then encoded by :func:`_encode_json`, which repeats the walk when the
estimate was short.
"""

import codecs
import copy
import datetime
import decimal
import json
import math
import re
import sys
import traceback
import uuid
from collections.abc import Mapping
from functools import lru_cache

from opentelemetry.trace import Status, StatusCode

from .redact import REDACTED, _normalize, redact_text
from .tools import recordset_ids

# Reserved log record fields that are not sanitized
_RESERVED_LOG_RECORD_FIELDS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)

# JSON structural costs charged while walking. :func:`_encode_json` measures
# the encoded document afterwards and retries when the estimate was short.
_JSON_CONTAINER = 2  # ``{}`` or ``[]``
_JSON_SEPARATOR = 1  # comma between elements
_JSON_QUOTES = 2
# ``false`` is the longest of ``null``, ``true`` and ``false``.
_JSON_LITERAL = 5
_DEPTH_MARKER = "<max-depth>"
# ``_truncated`` / ``_omitted`` added when a mapping is cut.
_MAPPING_TRUNCATION_RESERVE = 40
_REDACTED_COST = len(REDACTED) + _JSON_QUOTES

_TRUNCATION_MARKER_RESERVE = 32
# Room for closing brackets and markers added after the budget ran out; the
# encoded payload is measured exactly afterwards.
_ENCODE_RESERVE = 256
_ENCODE_ATTEMPTS = 3
# A JSON document embedded in a string has its quotes escaped once more.
_EMBEDDED_JSON_SHARE = 0.85
# Strings up to ``max_event_bytes`` times this are parsed as JSON documents.
_JSON_PARSE_FACTOR = 8
# Text is redacted a little past the cut, so a secret crossing it is masked.
_REDACT_OVERLAP = 512
_MAX_INT_BITS = 256
_utf8_decoder = codecs.getincrementaldecoder("utf-8")
_encode_basestring = json.encoder.encode_basestring
_JSON_TEXT = re.compile(r"\s*[\[{]")
_JSON_BYTES = re.compile(rb"\s*[\[{]")


def _utf8_len(text):
    """Get the UTF-8 length of a text.

    Args:
        text (str): The text to get the UTF-8 length of (UTF-8 encoded)

    Returns:
        int: The UTF-8 length of the text
    """
    if text.isascii():
        return len(text)
    return len(text.encode("utf-8", "surrogatepass"))


def _json_cost(text):
    """Get the UTF-8 size of a text encoded as a JSON string.

    Args:
        text (str): The text to get the UTF-8 size of (UTF-8 encoded)

    Returns:
        int: The UTF-8 size of the text encoded as a JSON string
    """
    return _utf8_len(_encode_basestring(text))


def _valid_unicode(text):
    """
    Replace lone surrogates, which the OTLP exporter cannot encode.

    Args:
        text: The text to validate

    Returns:
        str: The validated unicode text
    """
    if text.isascii():
        return text
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")
    return text


def _fit_text(value, limit, omitted=0, max_chars=None, measure=_json_cost):
    """Return ``(text, cost)``: ``value`` cut so ``measure(text) <= limit``.

    ``omitted`` characters were already dropped from the end of ``value``.
    A cut adds ``...<truncated:N>`` with the number of dropped characters.
    ``measure`` is :func:`_json_cost` for a JSON string and :func:`_utf8_len`
    for a log message or an exception.

    Args:
        value (str): The text to fit
        limit (int): The limit to fit the text to (UTF-8 bytes)
        omitted (int): The number of characters already dropped from the end of the text
        max_chars (int): The maximum number of characters to keep
        measure (callable): The function to measure the cost of the text

    Returns:
        tuple: A tuple containing the fitted text and the cost of the text
    """
    if max_chars is None:
        max_chars = limit
    if not omitted and len(value) <= min(limit, max_chars):
        cost = measure(value)
        if cost <= limit:
            return value, cost
    total = len(value) + omitted
    keep = max(0, min(len(value), max_chars, limit - _TRUNCATION_MARKER_RESERVE))
    for _attempt in range(8):
        result = "%s...<truncated:%d>" % (value[:keep], total - keep)
        cost = measure(result)
        if cost <= limit or not keep:
            break
        # Wide characters and escapes take more than one byte each.
        keep = max(
            0, min(keep - 1, keep * (limit - _TRUNCATION_MARKER_RESERVE) // cost)
        )
    return result, cost


def _parse_limit(settings):
    """Get the parse limit for a settings.

    Args:
        settings (Settings): The settings to get the parse limit for

    Returns:
        int: The parse limit for the settings
    """
    return settings.max_event_bytes * _JSON_PARSE_FACTOR


def _payload_size(value, settings):
    """Return the UTF-8 size of a text payload when it is cheap to know.

    Args:
        value (str): The value to get the UTF-8 size of
        settings (Settings): The settings to get the UTF-8 size of the value for

    Returns:
        int: The UTF-8 size of the value
    """
    # Get the UTF-8 size of a bytes or bytearray
    if isinstance(value, bytes | bytearray):
        return len(value)
    # Get the UTF-8 size of a memoryview
    if isinstance(value, memoryview):
        return value.nbytes
    # Get the UTF-8 size of a string
    if isinstance(value, str):
        # Get the UTF-8 size of an ASCII string
        if value.isascii():
            return len(value)
        # Get the UTF-8 size of a non-ASCII string
        if len(value) <= _parse_limit(settings):
            return _utf8_len(value)
    return None


@lru_cache(maxsize=4096)
def _is_sensitive_key(key, redact_keys):
    """Check if a key is sensitive.

    Args:
        key (str): The key to check if it is sensitive
        redact_keys (list): The list of keys to check if the key is in

    Returns:
        bool: True if the key is sensitive, False otherwise
    """
    normalized = _normalize(key)
    return any(token in normalized for token in redact_keys)


class Budget:
    """UTF-8 byte budget shared by every value of one telemetry event."""

    __slots__ = ("item_limit", "keys", "remaining", "string_limit", "truncated")

    def __init__(self, limit, string_limit, item_limit, keys=None):
        """Initialize the budget.

        Args:
            limit (int): The limit of the budget (UTF-8 bytes)
            string_limit (int): The limit of the budget for strings (UTF-8 bytes)
            item_limit (int): The limit of the budget for items
            keys (dict): The keys to cache the information for
        """
        self.remaining = limit
        self.string_limit = string_limit
        self.item_limit = item_limit
        # ``{key: (sensitive, json_cost)}``. Rows of an API response repeat
        # the same keys; avoids hashing the redact_keys tuple for every value.
        self.keys = {} if keys is None else keys
        self.truncated = False

    @classmethod
    def for_settings(cls, settings):
        """Budget of one log record: event bytes, attribute length, item cap.

        Args:
            settings (Settings): The settings to get the budget for

        Returns:
            Budget: The budget for the settings
        """
        return cls(
            settings.max_event_bytes,
            settings.max_attribute_length,
            settings.max_collection_items,
        )

    def key_info(self, key, redact_keys):
        """Return ``(sensitive, json_cost)`` for ``key``, cached on this budget.

        Args:
            key (str): The key to get the information for
            redact_keys (list): The list of keys to check if the key is in

        Returns:
            tuple: A tuple containing the sensitive flag and the JSON cost for the key
        """
        info = self.keys.get(key)
        if info is None:
            info = (
                _is_sensitive_key(key, redact_keys),
                _json_cost(key) + _JSON_QUOTES,
            )
            self.keys[key] = info
        return info

    def key_cost(self, key, redact_keys):
        """UTF-8 size of ``key`` as a JSON object key, including the quotes.

        Args:
            key (str): The key to get the cost for
            redact_keys (list): The list of keys to check if the key is in

        Returns:
            int: The UTF-8 size of the key as a JSON object key, including the quotes
        """
        return self.key_info(key, redact_keys)[1]

    def charge(self, size):
        """Charge the budget with a size.

        Args:
            size (int): The size to charge the budget with
        """
        self.remaining -= size

    def text_limit(self):
        """Get the text limit for the budget.

        Returns:
            int: The text limit for the budget
        """
        return max(0, min(self.string_limit, self.remaining))


def _redact_window(text, redact_keys, limit):
    """Return ``(redacted_head, head_length)``.

    Up to ``limit`` characters are kept, plus a short overlap so a secret
    that crosses the cut is still masked. ``head_length`` is measured before
    redaction; masking a secret changes the text length.

    Args:
        text (str): The text to redact
        redact_keys (list): The list of keys to redact
        limit (int): The limit to redact the text to

    Returns:
        tuple: A tuple containing the redacted head and the length of the head
    """
    head = text if len(text) <= limit else text[: limit + _REDACT_OVERLAP]
    return _valid_unicode(redact_text(head, redact_keys)), len(head)


def _clip_text(text, redact_keys, char_limit, byte_limit, total=None):
    """Redact plain text and cut it to ``char_limit`` chars and ``byte_limit``.

    The size is raw UTF-8. Log messages and exception text use this path.

    Args:
        text (str): The text to redact
        redact_keys (list): The list of keys to redact
        char_limit (int): The limit to redact the text to in characters
        byte_limit (int): The limit to redact the text to in bytes
        total (int): The total length of the text

    Returns:
        str: The redacted text
    """
    redacted, head_length = _redact_window(text, redact_keys, char_limit)
    full = len(text) if total is None else total
    result, _cost = _fit_text(
        redacted,
        max(0, byte_limit),
        full - head_length,
        char_limit,
        measure=_utf8_len,
    )
    return result


def _fit_json_string(text, settings, budget, omitted=0):
    """Redact ``text`` and cut it so its JSON encoding fits ``budget``.

    ``omitted`` characters were already dropped, for example the tail of a
    byte string that was not decoded.

    Args:
        text (str): The text to fit
        settings (Settings): The settings to fit the text to
        budget (Budget): The budget to fit the text to
        omitted (int): The number of characters already dropped from the end of the text

    Returns:
        str: The fitted text
    """
    limit = budget.text_limit()
    if not omitted and len(text) <= limit:
        redacted = redact_text(text, settings.redact_keys)
        escaped = _encode_basestring(redacted)
        if escaped.isascii():
            cost = len(escaped)
        else:
            redacted = _valid_unicode(redacted)
            cost = _json_cost(redacted)
        if cost <= limit:
            budget.charge(cost)
            return redacted
        text = redacted
    redacted, head_length = _redact_window(text, settings.redact_keys, limit)
    result, cost = _fit_text(redacted, limit, omitted + len(text) - head_length)
    if result is not redacted:
        budget.truncated = True
    budget.charge(cost)
    return result


def _embedded_json(key, text, settings, depth, budget):
    """Sanitize a JSON document passed as a string; keep it a string.

    Returns ``None`` when ``text`` is not JSON. The inner walk uses its own
    byte budget (a fraction of the string limit) and the caller's key cache.
    The fraction is not the retry used by :func:`_encode_json`: a string is
    quoted again when the document is embedded.

    Args:
        key (str): The key to sanitize the JSON document for
        text (str): The text to sanitize the JSON document from
        settings (Settings): The settings to sanitize the JSON document with
        depth (int): The depth of the JSON document
        budget (Budget): The budget to sanitize the JSON document with

    Returns:
        str: The sanitized JSON document
    """
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        return None
    limit = budget.text_limit()
    share = _EMBEDDED_JSON_SHARE
    for _attempt in range(2):
        inner = Budget(int(limit * share), limit, budget.item_limit, budget.keys)
        sanitized = _convert(key, parsed, settings, depth, inner)
        encoded = _valid_unicode(
            json.dumps(
                sanitized, ensure_ascii=False, separators=(",", ":"), default=str
            )
        )
        cost = _json_cost(encoded)
        if cost <= limit:
            budget.truncated = budget.truncated or inner.truncated
            budget.charge(cost)
            return encoded
        share *= limit / cost * 0.9
    # Secrets are already masked; only the length is cut here.
    result, cost = _fit_text(encoded, limit)
    budget.truncated = True
    budget.charge(cost)
    return result


def _binary(key, value, settings, budget, depth):
    """Decode bytes. A JSON document is sanitized; other text is clipped.

    Args:
        key (str): The key to decode the bytes for
        value (bytes | bytearray | memoryview): The bytes to decode
        settings (Settings): The settings to decode the bytes with
        budget (Budget): The budget to decode the bytes with
        depth (int): The depth of the bytes

    Returns:
        str: The decoded bytes
    """
    size = value.nbytes if isinstance(value, memoryview) else len(value)
    if size <= _parse_limit(settings) and _JSON_BYTES.match(bytes(value[:64])):
        try:
            text = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None:
            return _text(key, text, settings, budget, depth)
    head = bytes(value[: budget.text_limit() + _REDACT_OVERLAP])
    try:
        # A multi-byte character cut by the slice is buffered, not an error.
        text = _utf8_decoder().decode(head, False)
    except UnicodeDecodeError:
        result = "<bytes:%d>" % size
        budget.charge(len(result) + _JSON_QUOTES)
        return result
    return _fit_json_string(text, settings, budget, size - len(head))


def _text(key, text, settings, budget, depth):
    """Sanitize a string, parsing it when it holds a JSON document.

    Args:
        key (str): The key to sanitize the string for
        text (str): The text to sanitize the string from
        settings (Settings): The settings to sanitize the string with
        budget (Budget): The budget to sanitize the string with
        depth (int): The depth of the string

    Returns:
        str: The sanitized string
    """
    if (
        text
        and (text[0] in "{[" or (text[0].isspace() and _JSON_TEXT.match(text)))
        and len(text) <= _parse_limit(settings)
    ):
        result = _embedded_json(key, text, settings, depth, budget)
        if result is not None:
            return result
    return _fit_json_string(text, settings, budget)


def _charge_quoted(budget, text):
    """Charge ``text`` as a JSON string and return it.

    Args:
        budget (Budget): The budget to charge the text with
        text (str): The text to charge as a JSON string

    Returns:
        str: The charged text
    """
    budget.charge(len(text) + _JSON_QUOTES)
    return text


def _bounded_int(value, budget):
    """Charge an integer as a JSON string and return it.

    Args:
        value (int): The integer to charge
        budget (Budget): The budget to charge the integer with

    Returns:
        str | int: The charged integer
    """
    if value.bit_length() > _MAX_INT_BITS:
        return _charge_quoted(budget, "<int:%d bits>" % value.bit_length())
    budget.charge(len(int.__repr__(value)))
    return value


def _finite_float(value, budget):
    """Charge a finite float as a JSON string and return it.

    Args:
        value (float): The float to charge
        budget (Budget): The budget to charge the float with

    Returns:
        str | float: The charged float
    """
    if math.isfinite(value):
        budget.charge(len(float.__repr__(value)))
        return value
    # NaN and Infinity are not valid JSON.
    return _charge_quoted(budget, float.__repr__(value))


def _max_depth(budget):
    """Set the truncated flag to True and charge
    the budget with the length of the depth marker.

    Args:
        budget (Budget): The budget to set the truncated flag for

    Returns:
        str: The depth marker
    """
    budget.truncated = True
    budget.charge(len(_DEPTH_MARKER) + _JSON_QUOTES)
    return _DEPTH_MARKER


def _convert(key, value, settings, depth, budget):
    """Return a JSON-friendly copy of ``value``. ``budget`` is required.

    A sensitive ``key`` is masked here, once. Callers that already know the
    key still come through this function: the lookup is cached on ``budget``.

    Args:
        key (str): The key to convert
        value (Any): The value to convert
        settings (Settings): The settings to convert the value with
        depth (int): The depth of the value
        budget (Budget): The budget to convert the value with

    Returns:
        Any: The converted value
    """
    # Check if the key is sensitive
    if budget.key_info(key, settings.redact_keys)[0]:
        budget.charge(_REDACTED_COST)
        return REDACTED
    # Convert the value to a string
    if isinstance(value, str):
        return _text(key, value, settings, budget, depth)
    if value is None or isinstance(value, bool):
        budget.charge(_JSON_LITERAL)
        return value
    # Convert the value to an integer
    if isinstance(value, int):
        return _bounded_int(value, budget)
    # Convert the value to a float
    if isinstance(value, float):
        return _finite_float(value, budget)
    # Convert the value to a bytes, bytearray or memoryview
    if isinstance(value, bytes | bytearray | memoryview):
        return _binary(key, value, settings, budget, depth)
    # Convert the value to a datetime, date or time
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        # Convert the value to an ISO format string
        return _charge_quoted(budget, value.isoformat())
    # Convert the value to a decimal or UUID
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return _charge_quoted(budget, str(value))
    # Check if the depth is greater than the maximum depth
    if depth >= settings.max_depth:
        # Set the truncated flag to True and charge
        # the budget with the length of the depth marker
        return _max_depth(budget)
    # Convert the value to a mapping
    if isinstance(value, Mapping):
        return _mapping(value, settings, depth, budget)
    # Convert the value to a list, tuple, set or frozenset
    if isinstance(value, list | tuple | set | frozenset):
        # Convert the value to a collection
        return _collection(key, value, settings, depth, budget)
    # Convert the value to an opaque object
    return _opaque(value, settings, budget)


def _mapping(value, settings, depth, budget):
    """Convert a mapping to a JSON-friendly format.

    Args:
        value (Mapping): The mapping to convert
        settings (Settings): The settings to convert the mapping with
        depth (int): The depth of the mapping
        budget (Budget): The budget to convert the mapping with

    Returns:
        dict: The converted mapping
    """
    result = {}
    budget.charge(_JSON_CONTAINER)
    redact_keys = settings.redact_keys
    item_limit = budget.item_limit
    for index, (nested_key, nested_value) in enumerate(value.items()):
        if index >= item_limit or budget.remaining <= 0:
            result["_truncated"] = True
            result["_omitted"] = len(value) - index
            budget.truncated = True
            budget.charge(_MAPPING_TRUNCATION_RESERVE)
            break
        nested_key = str(nested_key)
        budget.charge(budget.key_cost(nested_key, redact_keys))
        result[nested_key] = _convert(
            nested_key, nested_value, settings, depth + 1, budget
        )
    return result


def _collection(key, value, settings, depth, budget):
    """Convert a collection to a JSON-friendly format.

    Args:
        key (str): The key to convert the collection for
        value (list | tuple | set | frozenset): The collection to convert
        settings (Settings): The settings to convert the collection with
        depth (int): The depth of the collection
        budget (Budget): The budget to convert the collection with

    Returns:
        list: The converted collection
    """
    result = []
    budget.charge(_JSON_CONTAINER)
    item_limit = budget.item_limit
    for index, item in enumerate(value):
        if index >= item_limit or budget.remaining <= 0:
            marker = "<truncated:%d>" % (len(value) - index)
            result.append(marker)
            budget.truncated = True
            budget.charge(len(marker) + _JSON_QUOTES + _JSON_SEPARATOR)
            break
        budget.charge(_JSON_SEPARATOR)
        # ``key`` belongs to the collection. A sensitive key was masked before
        # this loop, so each item is walked under that same key.
        result.append(_convert(key, item, settings, depth + 1, budget))
    return result


def _opaque(value, settings, budget):
    """Convert an opaque object to a JSON-friendly format.

    Args:
        value (Any): The opaque object to convert
        settings (Settings): The settings to convert the opaque object with
        budget (Budget): The budget to convert the opaque object with

    Returns:
        str: The converted opaque object
    """
    # Odoo recordsets can occasionally appear in custom method arguments.
    # Serialize only stable identity, never fields/cache/environment.
    model_name = getattr(value, "_name", None)
    if model_name:
        try:
            ids = recordset_ids(value, settings.max_collection_items)
        except Exception:
            ids = None
        if ids is not None:
            result = {"_type": "recordset", "model": str(model_name), "ids": ids}
            budget.charge(len(json.dumps(result, default=str)))
            return result

    # Avoid serializing requests, sessions and arbitrary objects.
    result = "<%s>" % type(value).__name__
    budget.charge(_json_cost(result))
    return result


def _encode_json(value, settings, limit):
    """Return ``(json_text, utf8_size, truncated)`` with ``utf8_size <= limit``.

    Strings and collections inside the payload are bounded by this byte
    budget, not by ``max_attribute_length`` or ``max_collection_items``.

    Args:
        value (Any): The value to encode as a JSON string
        settings (Settings): The settings to encode the value with
        limit (int): The limit to encode the value to

    Returns:
        tuple: A tuple containing the encoded JSON string,
        the UTF-8 size of the encoded JSON string and the truncated flag
    """
    budget_limit = max(0, limit - min(_ENCODE_RESERVE, limit // 8))
    size = 0
    for _attempt in range(_ENCODE_ATTEMPTS):
        # ``item_limit`` is the byte cap: a payload that fits is exported whole.
        budget = Budget(budget_limit, budget_limit, limit)
        sanitized = _convert("capture", value, settings, 0, budget)
        encoded = json.dumps(
            sanitized, ensure_ascii=False, separators=(",", ":"), default=str
        )
        size = _utf8_len(encoded)
        if size <= limit:
            return encoded, size, budget.truncated
        # The budget is an estimate; retry with a proportionally smaller one.
        budget_limit = int(budget_limit * limit / size * 0.9)
    encoded = json.dumps("<truncated:%d>" % size)
    if len(encoded) > limit:
        encoded = '"<truncated>"'
    return encoded, len(encoded), True


def _safe_str(exc):
    """Convert an exception to a string.

    Args:
        exc (Exception): The exception to convert

    Returns:
        str: The converted exception
    """
    try:
        return str(exc)
    except Exception:
        return "<unprintable %s>" % type(exc).__name__


def _format_exception(exc_type, exc, tb, limit):
    """Return the first ``limit`` chars of the traceback and its full length.

    The traceback of an integration error can repeat a large response body
    in every chained exception; it is never joined as a whole.

    Args:
        exc_type (Type[Exception]): The type of the exception
        exc (Exception): The exception to format
        tb (Traceback): The traceback to format
        limit (int): The limit to format the traceback to

    Returns:
        tuple: A tuple containing the formatted
        traceback and the total length of the traceback
    """
    parts = []
    kept = 0
    total = 0
    try:
        for chunk in traceback.TracebackException(exc_type, exc, tb).format():
            total += len(chunk)
            if kept < limit:
                piece = chunk[: limit - kept]
                parts.append(piece)
                kept += len(piece)
    except Exception:
        parts.append("<traceback unavailable>")
    return "".join(parts), max(total, kept)


def _exception_attributes(exc_type, exc, tb, settings, limit=None, stack_length=None):
    """Return sanitized ``exception.*`` attributes of about ``limit`` bytes.

    The message is bounded by ``max_attribute_length`` and the stacktrace
    by ``stack_length`` (``max_message_length`` by default). Both pass the
    text redaction rules: an integration error often carries a response
    body with credentials.

    Args:
        exc_type (Type[Exception]): The type of the exception
        exc (Exception): The exception to format
        tb (Traceback): The traceback to format
        settings (Settings): The settings to format the exception with
        limit (int): The limit to format the exception to
        stack_length (int): The length of the stacktrace

    Returns:
        dict: The sanitized exception attributes
    """
    keys = settings.redact_keys
    remaining = settings.max_event_bytes if limit is None else limit
    attributes = {}
    if exc_type is not None:
        attributes["exception.type"] = exc_type.__name__
        remaining -= len(exc_type.__name__)
    if exc is not None and exc.args:
        message = _clip_text(
            _safe_str(exc), keys, settings.max_attribute_length, remaining
        )
        attributes["exception.message"] = message
        remaining -= _utf8_len(message)
    if tb is not None:
        limit_chars = stack_length or settings.max_message_length
        text, total = _format_exception(
            exc_type, exc, tb, limit_chars + _REDACT_OVERLAP
        )
        attributes["exception.stacktrace"] = _clip_text(
            text, keys, limit_chars, max(0, remaining), total
        )
    return attributes


def _attach_exception(cloned, exc_info, settings, limit):
    """Export a bounded exception instead of letting the SDK format it.

    The SDK copies ``str(exc)`` and the full traceback without a limit or
    redaction; an integration error can carry a whole response body in
    its message. Returns the UTF-8 size of the exported attributes.

    Args:
        cloned (LogRecord): The log record to attach the exception to
        exc_info (tuple): The exception information to attach
        settings (Settings): The settings to attach the exception with
        limit (int): The limit to attach the exception to

    Returns:
        int: The UTF-8 size of the exported attributes
    """
    exc_type, exc, tb = exc_info
    cloned.exc_info = None
    cloned.exc_text = None
    attributes = _exception_attributes(exc_type, exc, tb, settings, limit)
    cloned.__dict__.update(attributes)
    return sum(_utf8_len(value) for value in attributes.values())


def _log_record(record, settings):
    """Return the sanitized clone and its approximate size in memory.

    One record shares one ``max_event_bytes`` budget in UTF-8 bytes: the
    message, the exception, plain extras, then captured payloads with
    whatever remains. The returned size also accounts for wide
    (non-Latin-1) strings, which take 2-4 bytes per character in memory.

    Args:
        record (LogRecord): The log record to sanitize
        settings (Settings): The settings to sanitize the log record with

    Returns:
        tuple: A tuple containing the sanitized
        log record and the approximate size in memory
    """
    cloned = copy.copy(record)

    try:
        message = record.getMessage()
    except Exception:
        message = str(record.msg)
    budget = Budget.for_settings(settings)
    cloned.msg = _clip_text(
        message,
        settings.redact_keys,
        settings.max_message_length,
        budget.remaining,
    )
    cloned.args = ()
    budget.charge(_utf8_len(cloned.msg))
    width = sys.getsizeof(cloned.msg) - len(cloned.msg)

    if record.exc_info:
        exception_cost = _attach_exception(
            cloned, record.exc_info, settings, max(0, budget.remaining)
        )
        budget.charge(exception_cost)

    captures = []
    attributes = cloned.__dict__
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_FIELDS:
            continue
        if isinstance(value, Capture):
            captures.append((key, value))
            continue
        # Extras are log attributes, not one JSON document, so the key is
        # charged as raw UTF-8 rather than as a JSON object key.
        budget.charge(_utf8_len(key))
        attributes[key] = _convert(key, value, settings, 0, budget)

    for key, capture in captures:
        rendered = capture.render(settings, max(0, budget.remaining))
        budget.charge(capture.size)
        width += sys.getsizeof(rendered) - len(rendered)
        attributes[key] = rendered
        if capture.truncated:
            attributes[key + ".truncated"] = True
            if capture.original_size is not None:
                attributes[key + ".original_size"] = capture.original_size

    size = settings.max_event_bytes - budget.remaining + width
    return cloned, size


class Capture:
    """Defer sanitization of a captured payload until a handler exports it.

    The payload is held by reference: nothing is copied or serialized when no
    handler exports the record. Other handlers only see the placeholder repr.
    After :meth:`render`, ``truncated`` tells whether the payload was cut and
    ``original_size`` holds the UTF-8 size of a cut text payload when known.
    """

    __slots__ = (
        "_factory",
        "_rendered",
        "_rendered_size",
        "_value",
        "name",
        "original_size",
        "truncated",
    )

    def __init__(self, name, value=None, factory=None):
        self.name = name
        self._value = value
        self._factory = factory
        self._rendered = None
        self._rendered_size = 0
        self.truncated = False
        self.original_size = None

    def __repr__(self):
        return "<odoo.capture>"

    __str__ = __repr__

    @property
    def size(self):
        """UTF-8 size of the last rendered JSON."""
        return self._rendered_size

    def render(self, settings, limit):
        """Return ``{name: payload}`` as sanitized JSON of <= ``limit`` UTF-8 bytes.

        The result is always valid JSON. It is reused by later records of the
        same call (for example the ``.error`` event) while it still fits their
        budget.

        Args:
            settings (Settings): The settings to render the capture with
            limit (int): The limit to render the capture to

        Returns:
            str: The rendered capture
        """
        rendered = self._rendered
        if rendered is not None and self._rendered_size <= limit:
            return rendered
        value = self._factory() if self._factory is not None else self._value
        rendered, size, truncated = Sanitazed._encode(
            {self.name: value}, settings, limit
        )
        self._rendered = rendered
        self._rendered_size = size
        self.truncated = truncated
        self.original_size = _payload_size(value, settings) if truncated else None
        return rendered


class Sanitazed:
    """Public entry points. The walk, the encoder and the log record live above."""

    @classmethod
    def log_record(cls, record, settings):
        """Clone and sanitize a LogRecord without changing Odoo's normal output.

        Args:
            record (LogRecord): The log record to sanitize
            settings (Settings): The settings to sanitize the log record with

        Returns:
            LogRecord: The sanitized log record
        """
        return cls.log_record_with_size(record, settings)[0]

    @classmethod
    def log_record_with_size(cls, record, settings):
        """Return the sanitized clone and its approximate size in memory.

        Args:
            record (LogRecord): The log record to sanitize
            settings (Settings): The settings to sanitize the log record with

        Returns:
            tuple: A tuple containing the sanitized
            log record and the approximate size in memory
        """
        return _log_record(record, settings)

    @classmethod
    def json(cls, value, settings, limit):
        """Return ``value`` sanitized and encoded as JSON of at most ``limit`` bytes.

        Inside the payload strings and collections are bounded by the budget
        only, so an API response that fits the budget is exported whole. The
        result is valid JSON even when the payload had to be cut.

        Args:
            value (Any): The value to sanitize and encode
            settings (Settings): The settings to sanitize and encode the value with
            limit (int): The limit to sanitize and encode the value to

        Returns:
            str: The sanitized and encoded value
        """
        return cls._encode(value, settings, limit)[0]

    @classmethod
    def _encode(cls, value, settings, limit):
        """Return ``(json_text, utf8_size, truncated)`` with ``utf8_size <= limit``.

        Args:
            value (Any): The value to encode
            settings (Settings): The settings to encode the value with
            limit (int): The limit to encode the value to

        Returns:
            tuple: A tuple containing the encoded JSON string,
            the UTF-8 size of the encoded JSON string and the truncated flag
        """
        return _encode_json(value, settings, limit)

    @classmethod
    def value(cls, key, value, settings, depth=0, budget=None):
        """Return a JSON-friendly copy of ``value`` safe to export as telemetry.

        Args:
            key (str): The key to convert the value for
            value (Any): The value to convert
            settings (Settings): The settings to convert the value with
            depth (int): The depth of the value
            budget (Budget): The budget to convert the value with

        Returns:
            Any: The converted value
        """
        if budget is None:
            budget = Budget.for_settings(settings)
        return _convert(key, value, settings, depth, budget)

    @classmethod
    def exception_attributes(
        cls, exc_type, exc, tb, settings, limit=None, stack_length=None
    ):
        """Return sanitized ``exception.*`` attributes of about ``limit`` bytes.

        Args:
            exc_type (Type[Exception]): The type of the exception
            exc (Exception): The exception to format
            tb (Traceback): The traceback to format
            settings (Settings): The settings to format the exception with
            limit (int): The limit to format the exception to
            stack_length (int): The length of the stacktrace

        Returns:
            dict: The sanitized exception attributes
        """
        return _exception_attributes(exc_type, exc, tb, settings, limit, stack_length)


def record_span_exception(span, exc, settings):
    """Mark ``span`` failed with a sanitized ``exception`` event.

    Replaces the SDK ``record_exception``/``set_status_on_exception``, which
    export ``str(exc)`` and the full traceback as is. Never raises.

    Args:
        span (Span): The span to mark as failed
        exc (Exception): The exception to mark as failed
        settings (Settings): The settings to mark the exception with
    """
    try:
        if not span.is_recording():
            return
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        attributes = Sanitazed.exception_attributes(
            type(exc),
            exc,
            exc.__traceback__,
            settings,
            stack_length=settings.max_attribute_length,
        )
        attributes["exception.escaped"] = True
        span.add_event("exception", attributes)
    except Exception:
        return

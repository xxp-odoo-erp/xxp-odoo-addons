# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import re
from functools import lru_cache

REDACTED = "***"
# Shorter text cannot hold a key, a separator and a value.
_MIN_LENGTH = 6
# An unterminated quoted value runs to the end of the text: the text may be a
# prefix cut from a longer body.
_VALUE = (
    r'\\"(?:[^"\\]|\\[^"])*(?:\\"|\Z)'
    r'|"(?:[^"\\]|\\.)*(?:"|\Z)'
    r"|'(?:[^'\\]|\\.)*(?:'|\Z)"
    r"|[^\s,;&\"'}\]<>)]+"
)
_SCHEME = re.compile(r"\b(bearer|basic|digest)[ \t]+[A-Za-z0-9._~+/=-]{6,}", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*")
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@'\"]+:[^/\s@'\"]+@")


def _normalize(key):
    return str(key).strip().lower().replace("-", "_").replace(".", "_")


def _key_pattern(normalized):
    # ``api_key`` also matches ``api-key``, ``api.key`` and ``apikey``.
    return "[_.-]?".join(re.escape(part) for part in normalized.split("_") if part)


@lru_cache(maxsize=16)
def _rules(redact_keys):
    """Return ``(hints, key_value)`` compiled for ``redact_keys``.

    ``hints`` are lowercase words one of which any match contains. A
    substring search is much faster than scanning long text with the regex.
    """
    names = {}
    for key in redact_keys:
        normalized = _normalize(key)
        squeezed = normalized.replace("_", "")
        if squeezed:
            names.setdefault(squeezed, normalized)
    normalized_names = set(names.values())
    # ``token`` already matches inside ``access_token``.
    kept = [
        name
        for name in normalized_names
        if not any(other != name and other in name for other in normalized_names)
    ]
    patterns = sorted((_key_pattern(name) for name in kept), key=len, reverse=True)
    words = {max(name.split("_"), key=len) for name in kept}
    hints = tuple(sorted(words | {"bearer", "basic", "digest", "eyj", "://"}))
    key_value = None
    if patterns:
        keys = "|".join(patterns)
        key_value = re.compile(
            rf"(?:{keys})[\w.-]*\\?[\"']?[ \t]*[:=][ \t]*(?P<value>{_VALUE})",
            re.I,
        )
    return hints, key_value


def _mask(match):
    value = match.group("value")
    if value.startswith('\\"'):
        masked = '\\"%s\\"' % REDACTED
    elif value[0] in "\"'":
        masked = value[0] + REDACTED + value[0]
    else:
        masked = REDACTED
    return match.group(0)[: match.start("value") - match.start()] + masked


def redact_text(text, redact_keys):
    """Mask credentials found in free text by explicit rules.

    Covers ``key=value``, ``key: value``, quoted and escaped JSON pairs whose
    key contains a ``redact_keys`` token, ``Bearer``/``Basic``/``Digest``
    credentials, JWTs and passwords in URLs. Free text has no structure, so
    this is a best effort and not a guarantee.
    """
    if len(text) < _MIN_LENGTH:
        return text
    # Every rule needs a separator, a space before the credential or a JWT.
    if not ("=" in text or ":" in text or " " in text or "\t" in text or "eyJ" in text):
        return text
    hints, key_value = _rules(tuple(redact_keys))
    lowered = text.lower()
    if not any(word in lowered for word in hints):
        return text
    text = _SCHEME.sub(r"\1 " + REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(REDACTED + "@", text)
    if key_value is not None:
        text = key_value.sub(_mask, text)
    return text

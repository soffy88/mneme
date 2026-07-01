"""redact_share_secrets — recursively redact sensitive strings from a payload dict."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"/[a-z]+/[a-z]+/[^\s]+"),
]

_REDACTED = "[REDACTED]"


def _redact_str(value: str) -> str:
    for pattern in _PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return redact_share_secrets(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_share_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with sensitive strings replaced by ``[REDACTED]``.

    Recursively scans all string values.  The original *payload* is not
    mutated.
    """
    return {key: _redact_value(val) for key, val in payload.items()}

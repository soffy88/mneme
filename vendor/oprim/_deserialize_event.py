"""deserialize_event — parse JSON bytes into an Event."""
from __future__ import annotations

import json

from ._hicode_types import Event

_REQUIRED = ("id", "type", "payload", "timestamp")


def deserialize_event(raw: bytes) -> Event:
    """Parse *raw* UTF-8 JSON bytes and return an :class:`Event`.

    Raises :class:`ValueError` on invalid JSON or missing required fields
    (``id``, ``type``, ``payload``, ``timestamp``).
    """
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"deserialize_event: invalid JSON bytes: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("deserialize_event: expected a JSON object at top level")

    missing = [f for f in _REQUIRED if f not in data]
    if missing:
        raise ValueError(f"deserialize_event: missing required fields: {missing}")

    return Event(
        id=data["id"],
        type=data["type"],
        payload=data["payload"],
        timestamp=data["timestamp"],
    )

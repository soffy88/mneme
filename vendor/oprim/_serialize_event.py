"""serialize_event — encode an Event to canonical JSON bytes."""
from __future__ import annotations

import json

from ._hicode_types import Event


def serialize_event(event: Event) -> bytes:
    """Return *event* serialized as UTF-8 JSON bytes."""
    data = {
        "id": event.id,
        "type": event.type,
        "payload": event.payload,
        "timestamp": event.timestamp,
    }
    return json.dumps(data, sort_keys=True).encode("utf-8")

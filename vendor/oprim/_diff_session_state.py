"""Compute the delta between two Session states."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Session, StateDelta


def diff_session_state(old: Session, *, new: Session) -> StateDelta:
    """Compare two sessions and return a StateDelta describing what changed.

    New messages are identified by position: any messages beyond the length
    of old.messages are considered new. A warning is set if the new session
    has fewer messages than the old one.
    """
    warning: str | None = None

    old_count = len(old.messages)
    new_count = len(new.messages)

    if new_count < old_count:
        warning = "message_count_decreased"
        new_messages = []
    else:
        new_messages = list(new.messages[old_count:])

    changed_fields: dict[str, Any] = {}
    for field_name in ("title", "model", "agent"):
        old_val = getattr(old, field_name)
        new_val = getattr(new, field_name)
        if old_val != new_val:
            changed_fields[field_name] = {"old": old_val, "new": new_val}

    return StateDelta(
        new_messages=new_messages,
        changed_fields=changed_fields,
        warning=warning,
    )

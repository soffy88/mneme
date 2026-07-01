"""Extract pinned messages from conversation history."""
from __future__ import annotations

from ._hicode_types import Message


def extract_pinned_messages(history: list[Message]) -> list[Message]:
    """Return all pinned messages from history, in original order.

    Args:
        history: Full conversation history as a list of Message.

    Returns:
        A new list containing only the messages where message.pinned is True,
        preserving their original relative order.
    """
    return [msg for msg in history if msg.pinned]

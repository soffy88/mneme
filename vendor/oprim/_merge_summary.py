"""Merge a compaction summary back into the message history tail."""
from __future__ import annotations

from ._hicode_types import Message, Part


def merge_summary(summary: str, *, tail: list[Message]) -> list[Message]:
    """Prepend a summary message to the tail of kept messages.

    Args:
        summary: Text produced by the compaction LLM call.
        tail: Messages that were retained verbatim (to_keep from Window).

    Returns:
        A new list: [summary_message] + tail copy, or just a tail copy
        when summary is empty.
    """
    tail_copy = list(tail)

    if not summary:
        return tail_copy

    summary_message = Message(
        role="assistant",
        parts=[Part(type="text", text=summary)],
    )

    return [summary_message] + tail_copy

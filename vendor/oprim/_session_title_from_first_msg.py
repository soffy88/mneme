"""Derive a session title from the first message."""
from __future__ import annotations

from ._hicode_types import Message


def session_title_from_first_msg(msg: Message, *, max_len: int = 50) -> str:
    """Extract a title from the first text part of a message.

    Collapses newlines to spaces and truncates to max_len characters,
    appending '...' if the text exceeds that length.
    Returns 'Untitled' if no text parts are present.
    """
    text: str | None = None
    for part in msg.parts:
        if part.type == "text" and part.text is not None:
            text = part.text
            break

    if text is None:
        return "Untitled"

    text = " ".join(text.splitlines())

    if len(text) > max_len:
        return text[:max_len] + "..."

    return text

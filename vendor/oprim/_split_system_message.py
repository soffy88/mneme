"""Split system Message objects out of a message list."""
from __future__ import annotations

from ._hicode_types import Message


def split_system_message(
    messages: list[Message], *, provider: str = ""
) -> tuple[str | None, list[Message]]:
    """Extract system messages from a list and return (system_text, remaining).

    System messages are identified by role == "system".
    Their text parts are concatenated with newlines into a single string.
    Non-system messages are returned in original order.
    If no system messages exist, returns (None, original_list).

    The provider parameter is accepted for API symmetry but does not alter
    behaviour — callers handle provider differences downstream.
    """
    system_texts: list[str] = []
    remaining: list[Message] = []

    for msg in messages:
        if msg.role == "system":
            for part in msg.parts:
                if part.type == "text" and part.text:
                    system_texts.append(part.text)
        else:
            remaining.append(msg)

    if not system_texts:
        return None, messages

    return "\n".join(system_texts), remaining

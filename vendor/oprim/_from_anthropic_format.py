"""Parse an Anthropic API response object into an internal Message."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message, Part, ToolCall


def from_anthropic_format(raw: dict[str, Any]) -> Message:
    """Parse an Anthropic API response into a Message.

    raw: single response object with "content" list and "role".
    """
    role = raw.get("role", "assistant")
    content_blocks = raw.get("content", [])
    parts: list[Part] = []

    for block in content_blocks:
        btype = block.get("type", "")
        if btype == "text":
            parts.append(Part(type="text", text=block.get("text", "")))
        elif btype == "thinking":
            parts.append(Part(type="reasoning", text=block.get("thinking", "")))
        elif btype == "tool_use":
            tc = ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                args=block.get("input", {}),
            )
            parts.append(Part(type="tool_call", tool_call=tc))

    return Message(role=role, parts=parts)

"""Parse a Google Gemini API response content object into an internal Message."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message, Part, ToolCall


def from_google_format(raw: dict[str, Any]) -> Message:
    """Parse a Google Gemini response candidate into a Message.

    raw: a candidates[N].content or content object with "role" and "parts".
    """
    g_role = raw.get("role", "model")
    role = "assistant" if g_role == "model" else g_role
    parts: list[Part] = []

    for p in raw.get("parts", []):
        if "text" in p:
            parts.append(Part(type="text", text=p["text"]))
        elif "functionCall" in p:
            fc = p["functionCall"]
            tc = ToolCall(
                id=fc.get("name", ""),
                name=fc.get("name", ""),
                args=fc.get("args", {}),
            )
            parts.append(Part(type="tool_call", tool_call=tc))

    return Message(role=role, parts=parts)

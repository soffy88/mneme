"""Parse an OpenAI chat completion message object into an internal Message."""
from __future__ import annotations

import json
from typing import Any

from ._hicode_types import Message, Part, ToolCall


def from_openai_format(raw: dict[str, Any]) -> Message:
    """Parse an OpenAI chat completion message into a Message.

    raw: a choices[N].message or message object with "role", "content",
         and optionally "tool_calls".
    """
    role = raw.get("role", "assistant")
    parts: list[Part] = []

    content = raw.get("content")
    if content:
        parts.append(Part(type="text", text=content))

    tool_calls = raw.get("tool_calls") or []
    for tc_raw in tool_calls:
        fn = tc_raw.get("function", {})
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            args = {}
        tc = ToolCall(
            id=tc_raw.get("id", ""),
            name=fn.get("name", ""),
            args=args,
        )
        parts.append(Part(type="tool_call", tool_call=tc))

    return Message(role=role, parts=parts)

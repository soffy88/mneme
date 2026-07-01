"""Convert internal Message list to Anthropic API request format."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message


def to_anthropic_format(messages: list[Message]) -> dict[str, Any]:
    """Convert a list of Messages to Anthropic API request format.

    System messages are extracted as a top-level "system" string.
    Remaining messages are converted to Anthropic's content block format.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            for part in msg.parts:
                if part.type == "text" and part.text:
                    system_parts.append(part.text)
            continue

        blocks: list[dict[str, Any]] = []
        for part in msg.parts:
            if part.type == "text":
                blocks.append({"type": "text", "text": part.text or ""})
            elif part.type == "reasoning":
                blocks.append({"type": "text", "text": part.text or ""})
            elif part.type == "tool_call" and part.tool_call is not None:
                tc = part.tool_call
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.args,
                })
            elif part.type == "tool_result" and part.tool_result is not None:
                tr = part.tool_result
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr.call_id,
                    "content": tr.content,
                })
            elif part.type == "image":
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.mime or "image/png",
                        "data": part.data or "",
                    },
                })

        role = "user" if msg.role == "user" else "assistant"
        converted.append({"role": role, "content": blocks})

    result: dict[str, Any] = {"messages": converted}
    if system_parts:
        result["system"] = "\n".join(system_parts)
    return result

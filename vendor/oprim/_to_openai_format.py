"""Convert internal Message list to OpenAI chat completion request format."""
from __future__ import annotations

import json
from typing import Any

from ._hicode_types import Message


def to_openai_format(messages: list[Message]) -> dict[str, Any]:
    """Convert a list of Messages to OpenAI chat completion request format."""
    converted: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.role  # user / assistant / system / tool

        # Collect tool_call parts and text parts separately for assistant messages
        if role == "assistant":
            text_parts = [p for p in msg.parts if p.type == "text"]
            tool_call_parts = [p for p in msg.parts if p.type == "tool_call"]

            content: str | None = None
            if text_parts:
                content = "".join(p.text or "" for p in text_parts)

            if tool_call_parts:
                tool_calls = []
                for p in tool_call_parts:
                    tc = p.tool_call
                    if tc is None:
                        continue
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    })
                entry: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
                if content is not None:
                    entry["content"] = content
                converted.append(entry)
            else:
                converted.append({"role": "assistant", "content": content or ""})

        elif role in ("user", "system"):
            text = "".join(p.text or "" for p in msg.parts if p.type == "text")
            converted.append({"role": role, "content": text})

        elif role == "tool":
            for p in msg.parts:
                if p.type == "tool_result" and p.tool_result is not None:
                    tr = p.tool_result
                    converted.append({
                        "role": "tool",
                        "tool_call_id": tr.call_id,
                        "content": tr.content,
                    })

    return {"messages": converted}

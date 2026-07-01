"""Convert internal Message list to Google Gemini API request format."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message


def to_google_format(messages: list[Message]) -> dict[str, Any]:
    """Convert a list of Messages to Google Gemini API request format.

    System messages are skipped (pass separately via systemInstruction).
    Role 'assistant' maps to 'model'.
    """
    contents: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            continue

        role = "model" if msg.role == "assistant" else "user"
        parts: list[dict[str, Any]] = []

        for p in msg.parts:
            if p.type == "text":
                parts.append({"text": p.text or ""})
            elif p.type == "tool_call" and p.tool_call is not None:
                tc = p.tool_call
                parts.append({
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.args,
                    }
                })
            elif p.type == "tool_result" and p.tool_result is not None:
                tr = p.tool_result
                parts.append({
                    "functionResponse": {
                        "name": tr.call_id,
                        "response": {"content": tr.content},
                    }
                })
            elif p.type == "image":
                parts.append({
                    "inlineData": {
                        "mimeType": p.mime or "image/png",
                        "data": p.data or "",
                    }
                })

        contents.append({"role": role, "parts": parts})

    return {"contents": contents}

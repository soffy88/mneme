"""Deserialize a plain dict back into a Session."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._hicode_types import Message, Part, Session, ToolCall, ToolResult


def _deserialize_part(d: dict[str, Any]) -> Part:
    tool_call = None
    if "tool_call" in d and d["tool_call"] is not None:
        tc = d["tool_call"]
        tool_call = ToolCall(id=tc["id"], name=tc["name"], args=tc["args"])

    tool_result = None
    if "tool_result" in d and d["tool_result"] is not None:
        tr = d["tool_result"]
        tool_result = ToolResult(
            call_id=tr["call_id"],
            content=tr["content"],
            is_error=tr.get("is_error", False),
        )

    path = None
    if "path" in d and d["path"] is not None:
        path = Path(d["path"])

    return Part(
        type=d["type"],
        text=d.get("text"),
        tool_call=tool_call,
        tool_result=tool_result,
        path=path,
        mime=d.get("mime"),
        data=d.get("data"),
        pinned=d.get("pinned", False),
    )


def _deserialize_message(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        parts=[_deserialize_part(p) for p in d.get("parts", [])],
        pinned=d.get("pinned", False),
    )


def deserialize_session(raw: dict[str, Any]) -> Session:
    """Reconstruct a Session from a plain dict produced by serialize_session."""
    if "id" not in raw or raw["id"] is None:
        raise ValueError("Missing required field: id")
    if "title" not in raw or raw["title"] is None:
        raise ValueError("Missing required field: title")
    if "messages" not in raw or raw["messages"] is None:
        raise ValueError("Missing required field: messages")
    if "created_at" not in raw or raw["created_at"] is None:
        raise ValueError("Missing required field: created_at")

    return Session(
        id=raw["id"],
        title=raw["title"],
        messages=[_deserialize_message(m) for m in raw["messages"]],
        created_at=raw["created_at"],
        model=raw.get("model", ""),
        agent=raw.get("agent", ""),
        version=raw.get("version", 1),
    )

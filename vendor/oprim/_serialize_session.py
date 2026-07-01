"""Serialize a Session to a plain JSON-serializable dict."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message, Part, Session


def _serialize_part(part: Part) -> dict[str, Any]:
    d: dict[str, Any] = {"type": part.type}
    if part.text is not None:
        d["text"] = part.text
    if part.tool_call is not None:
        d["tool_call"] = {
            "id": part.tool_call.id,
            "name": part.tool_call.name,
            "args": part.tool_call.args,
        }
    if part.tool_result is not None:
        d["tool_result"] = {
            "call_id": part.tool_result.call_id,
            "content": part.tool_result.content,
            "is_error": part.tool_result.is_error,
        }
    if part.path is not None:
        d["path"] = str(part.path)
    if part.mime is not None:
        d["mime"] = part.mime
    if part.data is not None:
        d["data"] = part.data
    if part.pinned:
        d["pinned"] = part.pinned
    return d


def _serialize_message(msg: Message) -> dict[str, Any]:
    return {
        "role": msg.role,
        "parts": [_serialize_part(p) for p in msg.parts],
        "pinned": msg.pinned,
    }


def serialize_session(session: Session) -> dict[str, Any]:
    """Convert a Session to a plain JSON-serializable dict."""
    return {
        "id": session.id,
        "title": session.title,
        "messages": [_serialize_message(m) for m in session.messages],
        "created_at": session.created_at,
        "model": session.model,
        "agent": session.agent,
        "version": session.version,
    }

"""serialize_share_payload — convert a Session to a shareable dict."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Session


def serialize_share_payload(session: Session) -> dict[str, Any]:
    """Return a share-safe dict representation of *session*.

    The result contains no local paths or credentials.  Only text parts are
    included in the ``messages`` list; binary / path parts are omitted.
    """
    messages: list[dict[str, Any]] = []
    for msg in session.messages:
        texts = [
            part.text
            for part in msg.parts
            if part.type == "text" and part.text is not None
        ]
        messages.append({"role": msg.role, "parts": texts})

    return {
        "title": session.title,
        "model": session.model,
        "messages": messages,
        "metadata": {
            "created_at": session.created_at,
            "agent": session.agent,
        },
    }

"""Generate a new session ID using UUID v7."""
from __future__ import annotations

from obase import uuid7


def new_session_id() -> str:
    """Return a new unique session ID as a string (UUID v7)."""
    return str(uuid7())

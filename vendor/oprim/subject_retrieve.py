"""oprim.subject_retrieve — Retrieve a Subject by subject_id."""
from __future__ import annotations

from typing import Any

from oprim._hevi_types import Subject


async def subject_retrieve(subject_id: str, *, store: Any = None) -> Subject | None:
    """Retrieve a Subject by its ID.

    Args:
        subject_id: The unique identifier of the subject.
        store: Optional dict store (same one passed to subject_create).

    Returns:
        The Subject if found, or None if not found. Never raises.
    """
    if store is not None:
        return store.get(subject_id)

    try:
        from oprim.subject_create import _MEMORY_STORE
        return _MEMORY_STORE.get(subject_id)
    except Exception:
        return None

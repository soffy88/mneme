"""oprim.subject_update — Update an existing Subject record."""
from __future__ import annotations

from typing import Any

from oprim._hevi_types import Subject


async def subject_update(
    subject_id: str,
    updates: dict,
    *,
    store: Any = None,
) -> Subject | None:
    """Apply updates to an existing Subject and persist the result.

    Args:
        subject_id: ID of the subject to update.
        updates: Dict of field names to new values.
        store: Optional dict store (same one passed to subject_create).

    Returns:
        The updated Subject, or None if the subject was not found.
    """
    # Resolve the store to use
    if store is not None:
        _store = store
    else:
        try:
            from oprim.subject_create import _MEMORY_STORE
            _store = _MEMORY_STORE
        except Exception:
            return None

    existing = _store.get(subject_id)
    if existing is None:
        return None

    # Build updated field dict, always increment version
    current_data = existing.model_dump()
    current_data.update(updates)
    current_data["version"] = existing.version + 1

    updated = Subject(**current_data)
    _store[subject_id] = updated
    return updated

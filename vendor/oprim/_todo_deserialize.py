"""Deserialize a plain dict produced by todo_serialize back to Todo objects."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Todo

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}

_REQUIRED_KEYS = {"id", "content", "status"}


def todo_deserialize(raw: dict[str, Any]) -> list[Todo]:
    """Reconstruct a list of :class:`Todo` instances from *raw*.

    Args:
        raw: Dict in the shape ``{"todos": [...]}`` as produced by
             :func:`todo_serialize`.

    Returns:
        List of :class:`Todo` instances.

    Raises:
        ValueError: If any todo entry is missing a required field
                    (``id``, ``content``, ``status``) or contains an
                    unrecognised status value.
    """
    entries = raw.get("todos", [])
    todos: list[Todo] = []
    for i, entry in enumerate(entries):
        missing = _REQUIRED_KEYS - entry.keys()
        if missing:
            raise ValueError(
                f"Todo entry at index {i} is missing required field(s): "
                + ", ".join(sorted(missing))
            )

        status = entry["status"]
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Todo entry at index {i} has unknown status {status!r}. "
                f"Expected one of: {sorted(VALID_STATUSES)}"
            )

        todos.append(
            Todo(
                id=entry["id"],
                content=entry["content"],
                status=status,
                priority=entry.get("priority", "medium"),
            )
        )
    return todos

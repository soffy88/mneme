"""Validate a list of Todo objects for internal consistency."""
from __future__ import annotations

from ._hicode_types import Todo

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


def todo_validate_state(todos: list[Todo]) -> bool:
    """Return True if *todos* represents a valid, consistent state.

    Rules:
    - Empty list is valid.
    - Every todo's status must be in VALID_STATUSES.
    - No duplicate ids.
    - At most one todo may have status ``in_progress``.

    Args:
        todos: List of :class:`Todo` instances to validate.

    Returns:
        ``True`` if all rules pass, ``False`` otherwise.
    """
    if not todos:
        return True

    seen_ids: set[str] = set()
    in_progress_count = 0

    for todo in todos:
        if todo.status not in VALID_STATUSES:
            return False

        if todo.id in seen_ids:
            return False
        seen_ids.add(todo.id)

        if todo.status == "in_progress":
            in_progress_count += 1
            if in_progress_count > 1:
                return False

    return True

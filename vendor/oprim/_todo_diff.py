"""Compute the delta between two snapshots of a Todo list."""
from __future__ import annotations

from ._hicode_types import Todo, TodoDelta


def todo_diff(old: list[Todo], *, new: list[Todo]) -> TodoDelta:
    """Return a :class:`TodoDelta` describing what changed between *old* and *new*.

    Comparison is performed by ``Todo.id``.

    - **added**: todos present in *new* but not in *old*.
    - **removed**: todos present in *old* but not in *new*.
    - **status_changed**: todos present in both but whose ``status`` differs;
      each entry is ``(new_todo, old_status)``.

    Args:
        old: Previous list of :class:`Todo` instances.
        new: Updated list of :class:`Todo` instances.

    Returns:
        A :class:`TodoDelta` with ``added``, ``removed``, and
        ``status_changed`` populated.
    """
    old_by_id: dict[str, Todo] = {t.id: t for t in old}
    new_by_id: dict[str, Todo] = {t.id: t for t in new}

    added: list[Todo] = [t for t in new if t.id not in old_by_id]
    removed: list[Todo] = [t for t in old if t.id not in new_by_id]
    status_changed: list[tuple[Todo, str]] = [
        (new_by_id[tid], old_todo.status)
        for tid, old_todo in old_by_id.items()
        if tid in new_by_id and new_by_id[tid].status != old_todo.status
    ]

    return TodoDelta(added=added, removed=removed, status_changed=status_changed)

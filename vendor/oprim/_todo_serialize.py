"""Serialize a list of Todo objects to a plain dict."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Todo


def todo_serialize(todos: list[Todo]) -> dict[str, Any]:
    """Return a JSON-friendly dict representation of *todos*.

    Args:
        todos: List of :class:`Todo` instances to serialize.

    Returns:
        ``{"todos": [{"id": ..., "content": ..., "status": ..., "priority": ...}, ...]}``
    """
    return {
        "todos": [
            {
                "id": todo.id,
                "content": todo.content,
                "status": todo.status,
                "priority": todo.priority,
            }
            for todo in todos
        ]
    }

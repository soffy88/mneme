"""Check whether a path is under one of a set of allowed roots."""
from __future__ import annotations

from pathlib import Path


def check_path_allowed(path: Path, *, roots: list[Path]) -> bool:
    """Return ``True`` if *path* is equal to or beneath any root in *roots*.

    Args:
        path: Path to check.
        roots: List of ``Path`` objects representing permitted root directories.
               An empty list always returns ``False``.

    Returns:
        ``True`` if the resolved *path* equals or is relative to at least one
        resolved root; ``False`` otherwise.
    """
    if not roots:
        return False

    path_resolved = path.resolve()

    for root in roots:
        root_resolved = root.resolve()
        if path_resolved == root_resolved or path_resolved.is_relative_to(root_resolved):
            return True

    return False

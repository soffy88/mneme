"""Pure-compute: sort_by_mtime."""
from __future__ import annotations

from ._hicode_types import FileEntry


def sort_by_mtime(entries: list[FileEntry], *, reverse: bool = True) -> list[FileEntry]:
    """Sort *entries* by their ``mtime`` field using a stable sort.

    Args:
        entries: List of :class:`~._hicode_types.FileEntry` objects.
        reverse: If ``True`` (default), newest (largest mtime) first.

    Returns:
        New sorted list; original is not mutated.
    """
    return sorted(entries, key=lambda e: e.mtime, reverse=reverse)

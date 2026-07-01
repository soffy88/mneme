"""Pure-compute: format_tree."""
from __future__ import annotations

from pathlib import Path

from ._hicode_types import Entry


def format_tree(entries: list[Entry], *, root: Path) -> str:
    """Render a list of :class:`~._hicode_types.Entry` objects as a tree string.

    Directories appear before files; within each group items are sorted
    alphabetically. Nested children are rendered recursively with
    ``├──`` / ``└──`` connectors.

    Args:
        entries: Top-level entries to render.
        root: Root path label shown on the first line.

    Returns:
        Multi-line tree string, or ``"(empty)"`` if *entries* is empty.
    """
    if not entries:
        return "(empty)"

    lines: list[str] = [str(root)]

    def _sort_key(e: Entry) -> tuple[int, str]:
        # Dirs (0) before files (1), then alphabetical
        return (0 if e.is_dir else 1, e.path.name.lower())

    def _render(items: list[Entry], prefix: str) -> None:
        sorted_items = sorted(items, key=_sort_key)
        for i, entry in enumerate(sorted_items):
            is_last = i == len(sorted_items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.path.name}")
            if entry.is_dir and entry.children:
                extension = "    " if is_last else "│   "
                _render(entry.children, prefix + extension)

    _render(entries, "")
    return "\n".join(lines)

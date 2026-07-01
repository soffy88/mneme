"""Pure-compute: detect_edit_conflict."""
from __future__ import annotations

from ._hicode_types import Conflict, Edit


def detect_edit_conflict(edits: list[Edit]) -> list[Conflict]:
    """Detect conflicts between edits that share the same ``old`` string.

    Two edits conflict when they have identical ``old`` values (including
    completely identical edits).

    Args:
        edits: List of :class:`~._hicode_types.Edit` objects.

    Returns:
        List of :class:`~._hicode_types.Conflict` objects, one per conflicting
        pair (a, b) where a < b.
    """
    if not edits:
        return []

    conflicts: list[Conflict] = []
    for i in range(len(edits)):
        for j in range(i + 1, len(edits)):
            if edits[i].old == edits[j].old:
                conflicts.append(Conflict(idx_a=i, idx_b=j))

    return conflicts

"""Pure-compute: plan_multiedit."""
from __future__ import annotations

from ._hicode_types import Edit, Patch


def plan_multiedit(original: str, *, edits: list[Edit]) -> list[Patch]:
    """Apply a sequence of edits and return a list of Patch records.

    Each edit is applied to the result of the previous one. If any edit's
    ``old`` string is not found, a :class:`ValueError` is raised indicating
    the index of the failing edit.

    Args:
        original: Starting text.
        edits: Ordered list of :class:`~._hicode_types.Edit` objects.

    Returns:
        List of :class:`~._hicode_types.Patch` objects, one per edit,
        recording the before/after text at that step.

    Raises:
        ValueError: If ``edit.old`` is not found in the current text.
    """
    if not edits:
        return []

    patches: list[Patch] = []
    current = original

    for idx, edit in enumerate(edits):
        if edit.old not in current:
            raise ValueError(
                f"edit[{idx}]: old string not found: {edit.old!r}"
            )
        before = current
        current = current.replace(edit.old, edit.new, 1)
        patches.append(Patch(old=before, new=current, idx=idx))

    return patches

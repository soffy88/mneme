"""Pure-compute: apply_string_replace."""
from __future__ import annotations


def apply_string_replace(original: str, *, old: str, new: str, count: int = 1) -> str:
    """Replace occurrences of *old* in *original* with *new*.

    Args:
        original: Source text.
        old: Substring to search for.
        new: Replacement text.
        count: Number of occurrences to replace. Negative means replace all.
               Zero returns *original* unchanged.

    Returns:
        Modified string.

    Raises:
        ValueError: If *old* is empty or not found in *original*.
    """
    if old == "":
        raise ValueError("old must not be empty")
    if count == 0:
        return original
    if old not in original:
        raise ValueError(f"not found: {old!r}")
    if count < 0:
        return original.replace(old, new)
    return original.replace(old, new, count)

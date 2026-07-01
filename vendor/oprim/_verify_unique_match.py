"""Pure-compute: verify_unique_match."""
from __future__ import annotations


def verify_unique_match(original: str, *, target: str) -> bool:
    """Return True if *target* appears exactly once in *original* (non-overlapping).

    Args:
        original: Source text to search.
        target: Substring to look for.

    Returns:
        True for exactly one match, False for zero or two-or-more matches.

    Raises:
        ValueError: If *target* is empty.
    """
    if target == "":
        raise ValueError("target must not be empty")
    count = original.count(target)
    return count == 1

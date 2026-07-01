"""Wildcard pattern matching using fnmatch semantics."""
from __future__ import annotations

import fnmatch


def match_wildcard_pattern(name: str, *, pattern: str) -> bool:
    """Return ``True`` if *name* matches *pattern*.

    Supports ``*`` (any sequence of characters) and ``?`` (any single
    character) via :func:`fnmatch.fnmatch`.

    Args:
        name: The string to test.
        pattern: Wildcard pattern.

    Returns:
        ``True`` if *name* matches *pattern*, ``False`` otherwise.
    """
    return fnmatch.fnmatch(name, pattern)

"""Pure-compute: apply_hunk."""
from __future__ import annotations

from ._parse_unified_diff import Hunk


def apply_hunk(original: str, *, hunk: Hunk) -> str:
    """Apply a single unified-diff *hunk* to *original*.

    Args:
        original: Source text (may be multi-line).
        hunk: A :class:`~._parse_unified_diff.Hunk` instance describing the change.

    Returns:
        Modified text.

    Raises:
        ValueError: If context lines do not match or line indices are out of bounds.
    """
    lines = original.splitlines(keepends=True)
    # old_start is 1-based
    pos = hunk.old_start - 1

    if pos < 0:
        raise ValueError(f"hunk old_start {hunk.old_start} is out of bounds")
    if pos > len(lines):
        raise ValueError(
            f"hunk old_start {hunk.old_start} exceeds file length {len(lines)}"
        )

    result: list[str] = list(lines[:pos])
    src_idx = pos

    for hunk_line in hunk.lines:
        if not hunk_line:
            continue
        prefix = hunk_line[0]
        content = hunk_line[1:]

        if prefix == " ":
            if src_idx >= len(lines):
                raise ValueError(
                    f"hunk context line {src_idx + 1} is out of bounds"
                )
            if lines[src_idx].rstrip("\n") != content.rstrip("\n"):
                raise ValueError(
                    f"context mismatch at line {src_idx + 1}: "
                    f"expected {content!r}, got {lines[src_idx]!r}"
                )
            result.append(lines[src_idx])
            src_idx += 1
        elif prefix == "-":
            if src_idx >= len(lines):
                raise ValueError(
                    f"deletion line {src_idx + 1} is out of bounds"
                )
            if lines[src_idx].rstrip("\n") != content.rstrip("\n"):
                raise ValueError(
                    f"deletion mismatch at line {src_idx + 1}: "
                    f"expected {content!r}, got {lines[src_idx]!r}"
                )
            src_idx += 1
        elif prefix == "+":
            if not content.endswith("\n"):
                content = content + "\n"
            result.append(content)

    result.extend(lines[src_idx:])
    return "".join(result)

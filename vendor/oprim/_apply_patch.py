"""Pure-compute: apply_patch."""
from __future__ import annotations

from ._parse_unified_diff import parse_unified_diff


def apply_patch(original: str, *, patch: str) -> str:
    """Apply a unified diff *patch* to *original*.

    Args:
        original: The text to patch.
        patch: Unified diff string (output of ``diff -u`` / ``git diff``).

    Returns:
        Patched text.

    Raises:
        ValueError: If a hunk's context lines do not match *original*.
    """
    if not patch or not patch.strip():
        return original

    file_diffs = parse_unified_diff(patch)
    if not file_diffs:
        return original

    lines = original.splitlines(keepends=True)

    for file_diff in file_diffs:
        for hunk in file_diff.hunks:
            # old_start is 1-based; convert to 0-based index
            pos = hunk.old_start - 1
            result: list[str] = list(lines[:pos])
            src_idx = pos

            for hunk_line in hunk.lines:
                if not hunk_line:
                    continue
                prefix = hunk_line[0]
                content = hunk_line[1:]

                if prefix == " ":
                    # Context line — verify it matches
                    if src_idx >= len(lines):
                        raise ValueError(
                            f"hunk failed at line {src_idx + 1}: source exhausted"
                        )
                    if lines[src_idx].rstrip("\n") != content.rstrip("\n"):
                        raise ValueError(
                            f"hunk failed at line {src_idx + 1}: "
                            f"expected {content!r}, got {lines[src_idx]!r}"
                        )
                    result.append(lines[src_idx])
                    src_idx += 1
                elif prefix == "-":
                    # Deletion — verify and skip
                    if src_idx >= len(lines):
                        raise ValueError(
                            f"hunk failed at line {src_idx + 1}: source exhausted"
                        )
                    if lines[src_idx].rstrip("\n") != content.rstrip("\n"):
                        raise ValueError(
                            f"hunk failed at line {src_idx + 1}: "
                            f"expected {content!r}, got {lines[src_idx]!r}"
                        )
                    src_idx += 1
                elif prefix == "+":
                    # Addition
                    if not content.endswith("\n"):
                        content = content + "\n"
                    result.append(content)

            # Append remaining lines after the hunk
            result.extend(lines[src_idx:])
            lines = result

    return "".join(lines)

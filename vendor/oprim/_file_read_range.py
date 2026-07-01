from __future__ import annotations


def file_read_range(content: str, *, start_line: int, end_line: int) -> str:
    """Extract lines [start_line, end_line] from content (1-based, closed interval)."""
    if start_line < 1:
        raise ValueError(f"start_line must be >= 1, got {start_line}")
    if start_line > end_line:
        raise ValueError(f"start_line ({start_line}) > end_line ({end_line})")
    if not content:
        return ""
    lines = content.splitlines(keepends=True)
    # clamp end_line to actual length
    end = min(end_line, len(lines))
    return "".join(lines[start_line - 1:end])

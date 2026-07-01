from __future__ import annotations


def add_line_numbers(text: str, *, start: int = 1, pad: int | None = None) -> str:
    """Prefix each line with right-aligned line number (read tool format)."""
    if start < 1:
        raise ValueError(f"start must be >= 1, got {start}")
    if not text:
        return ""
    lines = text.splitlines(keepends=True)
    end = start + len(lines) - 1
    width = pad if pad is not None else len(str(end))
    result = []
    for i, line in enumerate(lines):
        no = start + i
        result.append(f"{no:{width}}\t{line}")
    return "".join(result)

"""Pure-compute: parse_ripgrep_output."""
from __future__ import annotations

import json

from ._hicode_types import Hit


def parse_ripgrep_output(raw: str, *, format: str = "json") -> list[Hit]:
    """Parse ``rg --json`` output into a list of :class:`~._hicode_types.Hit` objects.

    Only lines with ``"type": "match"`` are processed. Lines that are not
    valid JSON or have a different type (begin/end/summary/context) are
    silently skipped.

    Args:
        raw: Raw stdout from ``rg --json``.
        format: Currently only ``"json"`` is supported (reserved for future use).

    Returns:
        List of :class:`~._hicode_types.Hit` objects.
    """
    hits: list[Hit] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(obj, dict):
            continue
        if obj.get("type") != "match":
            continue

        data = obj.get("data", {})
        path = data.get("path", {}).get("text", "")
        line_no = data.get("line_number", 0)

        submatches = data.get("submatches", [])
        col = submatches[0].get("start", 0) if submatches else 0

        lines_obj = data.get("lines", {})
        text = lines_obj.get("text", "").rstrip("\n")

        hits.append(Hit(path=path, line_no=line_no, col=col, text=text))

    return hits

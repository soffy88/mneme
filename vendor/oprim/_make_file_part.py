"""make_file_part — construct a file Part."""
from __future__ import annotations

from pathlib import Path

from ._hicode_types import Part


def make_file_part(path: Path, *, mime: str) -> Part:
    """Return a Part of type 'file'.

    Raises:
        ValueError: if *mime* is empty.
    """
    if not mime:
        raise ValueError("mime must not be empty")
    return Part(type="file", path=path, mime=mime)

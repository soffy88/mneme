"""make_text_part — construct a text Part."""
from __future__ import annotations

from ._hicode_types import Part


def make_text_part(text: str) -> Part:
    """Return a Part of type 'text'.

    Empty *text* is explicitly allowed.
    """
    return Part(type="text", text=text)

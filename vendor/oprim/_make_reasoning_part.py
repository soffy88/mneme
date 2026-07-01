"""make_reasoning_part — construct a reasoning Part."""
from __future__ import annotations

from ._hicode_types import Part


def make_reasoning_part(text: str) -> Part:
    """Return a Part of type 'reasoning'."""
    return Part(type="reasoning", text=text)

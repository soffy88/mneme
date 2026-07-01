"""make_image_part — construct an image Part."""
from __future__ import annotations

import base64

from ._hicode_types import Part


def make_image_part(data: str, *, mime: str) -> Part:
    """Return a Part of type 'image'.

    Raises:
        ValueError: if *mime* is empty or *data* is not valid base64.
    """
    if not mime:
        raise ValueError("mime must not be empty")
    try:
        base64.b64decode(data, validate=True)
    except Exception as exc:
        raise ValueError(f"data is not valid base64: {exc}") from exc
    return Part(type="image", data=data, mime=mime)

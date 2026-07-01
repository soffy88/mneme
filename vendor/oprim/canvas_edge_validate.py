"""oprim.canvas_edge_validate — Validate a canvas edge type compatibility. SYNC."""
from __future__ import annotations

COMPATIBLE: dict[tuple[str, str], bool] = {
    ("text", "image"): True,
    ("text", "video"): True,
    ("text", "audio"): True,
    ("text", "script"): True,
    ("image", "video"): True,
    ("image", "image"): True,
    ("image", "script"): True,
    ("audio", "video"): True,
    ("video", "video"): True,
    ("script", "image"): True,
    ("script", "video"): True,
}


def canvas_edge_validate(*, from_type: str, to_type: str) -> bool:
    """Return True if an edge from from_type to to_type is compatible.

    Args:
        from_type: Source node type (e.g. "text", "image").
        to_type: Target node type (e.g. "video", "audio").

    Returns:
        True if the edge is in the COMPATIBLE matrix, False otherwise.
    """
    return COMPATIBLE.get((from_type, to_type), False)

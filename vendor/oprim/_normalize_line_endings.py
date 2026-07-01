from __future__ import annotations


def normalize_line_endings(text: str, *, target: str = "\n") -> str:
    """Convert CRLF and CR to target line ending."""
    if target not in ("\n", "\r\n"):
        raise ValueError(f"Invalid target line ending: {target!r}")
    # First normalize all to LF, then convert to target
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if target == "\r\n":
        return normalized.replace("\n", "\r\n")
    return normalized

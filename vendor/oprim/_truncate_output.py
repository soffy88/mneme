"""Pure-compute: truncate_output."""
from __future__ import annotations


def truncate_output(text: str, *, max_bytes: int = 30_000) -> str:
    """Truncate *text* to at most *max_bytes* UTF-8 bytes.

    If the text fits within the limit it is returned unchanged. Otherwise
    the head and tail are kept and the middle is replaced with a marker
    of the form ``[... N bytes truncated ...]``. Multi-byte characters are
    never split.

    Args:
        text: Text to (potentially) truncate.
        max_bytes: Maximum allowed byte length of the result.

    Returns:
        Original or truncated string.

    Raises:
        ValueError: If *max_bytes* is <= 0.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    # Reserve bytes for the marker; use half/half split for head and tail.
    marker_template = "[... {} bytes truncated ...]"
    # Estimate marker length (will refine below)
    total = len(encoded)
    removed = total - max_bytes
    marker = marker_template.format(removed).encode("utf-8")
    marker_len = len(marker)

    available = max_bytes - marker_len
    if available <= 0:
        # Extreme case: just return the marker itself truncated to max_bytes
        return marker.decode("utf-8", errors="replace")[:max_bytes]

    head_bytes = available // 2
    tail_bytes = available - head_bytes

    # Decode head without splitting multi-byte chars
    head_enc = encoded[:head_bytes]
    # Walk back until valid UTF-8
    while head_bytes > 0:
        try:
            head_str = head_enc.decode("utf-8")
            break
        except UnicodeDecodeError:
            head_bytes -= 1
            head_enc = encoded[:head_bytes]
    else:
        head_str = ""

    # Decode tail without splitting multi-byte chars
    tail_start = total - tail_bytes
    tail_enc = encoded[tail_start:]
    while tail_bytes > 0:
        try:
            tail_str = tail_enc.decode("utf-8")
            break
        except UnicodeDecodeError:
            tail_bytes -= 1
            tail_start = total - tail_bytes
            tail_enc = encoded[tail_start:]
    else:
        tail_str = ""

    actual_removed = total - len(head_enc) - len(tail_enc)
    marker_str = marker_template.format(actual_removed)
    return head_str + marker_str + tail_str

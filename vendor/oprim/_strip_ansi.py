"""Pure-compute: strip_ansi."""
from __future__ import annotations

import re

# Matches CSI sequences (\x1b[ ... final-byte) and other common ESC sequences.
_ANSI_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-9;]*[A-Za-z]"   # CSI sequences: ESC [ ... letter  (covers SGR, cursor moves, etc.)
    r"|"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences: ESC ] ... BEL or ST
    r"|"
    r"[^[\]]"               # Two-char ESC sequences: ESC + single char (not [ or ])
    r")"
)


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*.

    Handles CSI (including SGR colour codes, cursor movement), OSC
    sequences, and simple two-character ESC sequences.

    Args:
        text: Input string potentially containing ANSI escapes.

    Returns:
        Clean string with all escape sequences removed.
    """
    return _ANSI_RE.sub("", text)

"""Select which messages to compact vs keep in context."""
from __future__ import annotations

from ._hicode_types import Message, Window


def select_compaction_window(
    history: list[Message],
    *,
    keep_recent: int = 10,
) -> Window:
    """Partition history into messages to compact and messages to keep.

    Args:
        history: Full conversation history as a list of Message.
        keep_recent: Number of non-pinned messages to retain verbatim
            (from the tail of history). Must be >= 0.

    Returns:
        Window with to_compact and to_keep lists.

    Raises:
        ValueError: If keep_recent < 0.
    """
    if keep_recent < 0:
        raise ValueError(f"keep_recent must be >= 0, got {keep_recent!r}")

    pinned: list[Message] = []
    non_pinned: list[Message] = []

    for msg in history:
        if msg.pinned:
            pinned.append(msg)
        else:
            non_pinned.append(msg)

    # Keep the most-recent keep_recent non-pinned messages verbatim.
    if keep_recent == 0:
        recent: list[Message] = []
        older: list[Message] = non_pinned
    else:
        recent = non_pinned[-keep_recent:]
        older = non_pinned[:-keep_recent]

    to_compact = older
    to_keep = pinned + recent

    return Window(to_compact=to_compact, to_keep=to_keep)

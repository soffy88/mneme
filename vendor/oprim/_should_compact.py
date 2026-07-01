"""Decide whether the conversation history needs compaction."""
from __future__ import annotations

from ._hicode_types import Message


def should_compact(
    history: list[Message],
    *,
    budget_tokens: int,
    model: str,
) -> bool:
    """Return True when the estimated token count exceeds 80 % of the budget.

    Token estimation: each text part contributes len(part.text) // 4 tokens.
    Non-text parts contribute 0 tokens.

    Args:
        history: Full conversation history as a list of Message.
        budget_tokens: Maximum token budget for the context window. Must be > 0.
        model: Model identifier (reserved for future per-model calibration).

    Returns:
        True if compaction is recommended, False otherwise.

    Raises:
        ValueError: If budget_tokens <= 0.
    """
    if budget_tokens <= 0:
        raise ValueError(f"budget_tokens must be > 0, got {budget_tokens!r}")

    if not history:
        return False

    total = 0
    for msg in history:
        for part in msg.parts:
            if part.type == "text" and part.text:
                total += len(part.text) // 4

    return total > budget_tokens * 0.8

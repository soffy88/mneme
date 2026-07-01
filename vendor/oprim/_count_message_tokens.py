"""Count estimated tokens for a list of Messages."""
from __future__ import annotations

import json

from ._estimate_tokens import estimate_tokens
from ._hicode_types import Message

# Tokens added per message to account for role marker and structural framing.
_OVERHEAD_PER_MESSAGE = 4

# Fixed token costs for image parts (no pixel data available at this layer).
_IMAGE_TOKENS_CLAUDE = 1600
_IMAGE_TOKENS_DEFAULT = 1000


def count_message_tokens(messages: list[Message], *, model: str) -> int:
    """Estimate the total token count for a list of *messages*.

    Each message incurs a fixed overhead of 4 tokens (role framing).  Part
    costs are then added per content block:

    * **text / reasoning** parts  — ``estimate_tokens(text, model=model)``
    * **image** parts             — 1 600 tokens for Claude models, 1 000 for others
    * **tool_call** parts         — tokens estimated from the JSON-serialised args
    * **tool_result** parts       — tokens estimated from the result content string
    * **file** parts              — tokens estimated from ``part.text`` if present

    Parameters
    ----------
    messages:
        Sequence of :class:`~oprim._hicode_types.Message` objects.
    model:
        Model identifier string used to tune per-part estimates.

    Returns
    -------
    int
        Total estimated token count, always >= 0.
    """
    if not messages:
        return 0

    is_claude = "claude" in model.lower()
    image_tokens = _IMAGE_TOKENS_CLAUDE if is_claude else _IMAGE_TOKENS_DEFAULT

    total = 0
    for message in messages:
        total += _OVERHEAD_PER_MESSAGE
        for part in message.parts:
            ptype = part.type

            if ptype == "image":
                total += image_tokens

            elif ptype == "tool_call":
                if part.tool_call is not None:
                    args_str = json.dumps(part.tool_call.args, ensure_ascii=False)
                    total += estimate_tokens(args_str, model=model)

            elif ptype == "tool_result":
                if part.tool_result is not None:
                    total += estimate_tokens(part.tool_result.content, model=model)

            else:
                # text, reasoning, file, or any unknown part with text content
                if part.text:
                    total += estimate_tokens(part.text, model=model)

    return total

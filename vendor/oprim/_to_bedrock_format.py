"""Convert internal Message list to Anthropic-on-Bedrock request format."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Message
from ._to_anthropic_format import to_anthropic_format


def to_bedrock_format(messages: list[Message]) -> dict[str, Any]:
    """Convert a list of Messages to Anthropic-on-Bedrock request format.

    Bedrock's Anthropic wrapper uses the same structure as the Anthropic API:
    {"messages": [...], "system": "..."}
    """
    return to_anthropic_format(messages)

"""Normalize provider-specific stop reasons to a unified StopReason."""
from __future__ import annotations

from typing import Any

from ._hicode_types import StopReason

_ANTHROPIC_MAP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
}

_OPENAI_MAP: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}

_GOOGLE_MAP: dict[str, StopReason] = {
    "STOP": "end_turn",
    "MAX_TOKENS": "max_tokens",
}


def normalize_stop_reason(raw: dict[str, Any], *, provider: str) -> StopReason:
    """Map a provider-specific stop reason field to a unified StopReason.

    Missing field defaults to "end_turn". Unknown value returns "unknown".
    """
    if provider == "anthropic":
        value = raw.get("stop_reason")
        if value is None:
            return "end_turn"
        return _ANTHROPIC_MAP.get(value, "unknown")

    if provider == "openai":
        value = raw.get("finish_reason")
        if value is None:
            return "end_turn"
        return _OPENAI_MAP.get(value, "unknown")

    if provider == "google":
        value = raw.get("finishReason")
        if value is None:
            return "end_turn"
        return _GOOGLE_MAP.get(value, "unknown")

    value = raw.get("stop_reason") or raw.get("finish_reason") or raw.get("finishReason")
    if value is None:
        return "end_turn"
    return "unknown"

"""Parse provider-specific stop/finish reason from a raw response dict."""
from __future__ import annotations

from typing import Any

from ._hicode_types import StopReason

# Per-provider value → StopReason maps (inlined to avoid circular imports)
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
    "TOOL_CODE": "tool_use",
}

_SUPPORTED_PROVIDERS = {"anthropic", "openai", "google"}


def parse_stop_reason(raw: dict[str, Any], *, provider: str) -> StopReason:
    """Extract and normalise the stop reason from a raw provider response.

    Parameters
    ----------
    raw:
        Raw response dictionary from the provider.
    provider:
        One of ``"anthropic"``, ``"openai"``, or ``"google"``.

    Returns
    -------
    StopReason
        Normalised stop reason.  Defaults to ``"end_turn"`` when the field is
        absent.  Returns ``"unknown"`` for unrecognised values.

    Raises
    ------
    ValueError
        If *provider* is not one of the supported values.
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unknown provider {provider!r}: must be one of {sorted(_SUPPORTED_PROVIDERS)}"
        )

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

    # provider == "google"
    value = raw.get("finishReason")
    if value is None:
        return "end_turn"
    return _GOOGLE_MAP.get(value, "unknown")

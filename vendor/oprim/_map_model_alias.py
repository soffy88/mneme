"""Map short model aliases to canonical model IDs per provider."""
from __future__ import annotations

_ANTHROPIC_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

_OPENAI_ALIASES: dict[str, str] = {
    "gpt4": "gpt-4o",
    "gpt4o": "gpt-4o",
}


def map_model_alias(alias: str, *, provider: str) -> str:
    """Resolve a short model alias to a canonical model ID.

    Empty alias raises ValueError.
    Unknown alias is returned as-is (assumed to already be a real model ID).
    Unknown provider returns alias as-is.
    """
    if not alias:
        raise ValueError("alias must be a non-empty string")

    if provider == "anthropic":
        return _ANTHROPIC_ALIASES.get(alias, alias)

    if provider == "openai":
        return _OPENAI_ALIASES.get(alias, alias)

    return alias

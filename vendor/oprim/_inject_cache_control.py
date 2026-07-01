"""Inject Anthropic prompt-caching cache_control markers into a payload."""
from __future__ import annotations

import copy
from typing import Any

_EPHEMERAL = {"type": "ephemeral"}


def _has_cache_control(block: dict[str, Any]) -> bool:
    return "cache_control" in block


def inject_cache_control(payload: dict[str, Any], *, provider: str) -> dict[str, Any]:
    """Return a copy of payload with cache_control injected for Anthropic.

    Only "anthropic" is supported; other providers receive an unchanged copy.

    For anthropic:
    - Inject cache_control on the last system block (if system is a list).
    - Inject cache_control on the last content block of the last user message.
    - Idempotent: blocks that already carry cache_control are not modified.
    """
    result = copy.deepcopy(payload)

    if provider != "anthropic":
        return result

    # Patch last system block if system is a list of blocks
    system = result.get("system")
    if isinstance(system, list) and system:
        last = system[-1]
        if not _has_cache_control(last):
            last["cache_control"] = _EPHEMERAL

    # Patch last content block of the last user message
    messages = result.get("messages", [])
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if user_indices:
        last_user = messages[user_indices[-1]]
        content = last_user.get("content", [])
        if isinstance(content, list) and content:
            last_block = content[-1]
            if not _has_cache_control(last_block):
                last_block["cache_control"] = _EPHEMERAL

    return result

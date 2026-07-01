"""Parse provider-specific raw LLM response dicts into ToolCall objects."""
from __future__ import annotations

import json
from typing import Any

from ._hicode_types import ToolCall

_SUPPORTED_PROVIDERS = {"anthropic", "openai"}


def parse_tool_calls(raw: dict[str, Any], *, provider: str) -> list[ToolCall]:
    """Extract tool calls from a raw provider response dict.

    Parameters
    ----------
    raw:
        The raw response dictionary returned by the provider.
    provider:
        One of ``"anthropic"`` or ``"openai"``.

    Returns
    -------
    list[ToolCall]
        Parsed tool calls, or an empty list when none are present.

    Raises
    ------
    ValueError
        If *provider* is not recognised, or if a tool call contains invalid
        JSON in its arguments field.
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unknown provider {provider!r}: must be one of {sorted(_SUPPORTED_PROVIDERS)}"
        )

    if provider == "anthropic":
        content: list[dict[str, Any]] = raw.get("content") or []
        result: list[ToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            call_id: str = block.get("id", "")
            name: str = block.get("name", "")
            args: Any = block.get("input", {})
            if not isinstance(args, dict):
                # Should not happen with a well-formed response, but guard it.
                try:
                    args = json.loads(args) if isinstance(args, str) else {}
                except (json.JSONDecodeError, TypeError):
                    raise ValueError(f"invalid args JSON for tool {name}")
            result.append(ToolCall(id=call_id, name=name, args=args))
        return result

    # provider == "openai"
    tool_calls: list[dict[str, Any]] = raw.get("tool_calls") or []
    result = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        call_id = tc.get("id", "")
        func: dict[str, Any] = tc.get("function") or {}
        name = func.get("name", "")
        raw_args: Any = func.get("arguments", "{}")
        if isinstance(raw_args, dict):
            args = raw_args
        else:
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                raise ValueError(f"invalid args JSON for tool {name}")
        result.append(ToolCall(id=call_id, name=name, args=args))
    return result

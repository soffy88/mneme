"""Apply provider-specific payload patches to work around API quirks."""
from __future__ import annotations

import copy
from typing import Any


def patch_provider_quirk(payload: dict[str, Any], *, provider: str) -> dict[str, Any]:
    """Return a patched copy of payload with provider-specific fixes applied.

    Never mutates the input dict.

    anthropic: ensure "system" is a non-empty string (set to " " if missing/empty).
    openai: remove messages where content is an empty string.
    google: merge consecutive same-role content entries.
    other: return a shallow copy unchanged.
    """
    result = copy.deepcopy(payload)

    if provider == "anthropic":
        system = result.get("system", "")
        if not system or not system.strip():
            result["system"] = " "
        return result

    if provider == "openai":
        messages = result.get("messages", [])
        result["messages"] = [
            m for m in messages
            if m.get("content") != ""
        ]
        return result

    if provider == "google":
        contents = result.get("contents", [])
        merged: list[dict[str, Any]] = []
        for entry in contents:
            if merged and merged[-1]["role"] == entry["role"]:
                merged[-1]["parts"] = merged[-1]["parts"] + entry.get("parts", [])
            else:
                merged.append(copy.deepcopy(entry))
        result["contents"] = merged
        return result

    return result

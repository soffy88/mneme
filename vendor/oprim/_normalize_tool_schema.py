"""Normalize internal tool schema dicts to provider-specific formats."""
from __future__ import annotations

from typing import Any


def normalize_tool_schema(tools: list[dict[str, Any]], *, provider: str) -> list[dict[str, Any]]:
    """Convert internal tool dicts to provider-specific format.

    Internal format: {name, description, parameters}

    Supported providers: "openai", "anthropic", "google"
    """
    if not tools:
        return []

    if provider == "openai":
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                },
            }
            for t in tools
        ]

    if provider == "anthropic":
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {}),
            }
            for t in tools
        ]

    if provider == "google":
        return [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    }
                    for t in tools
                ]
            }
        ]

    raise ValueError(f"Unknown provider: {provider!r}")

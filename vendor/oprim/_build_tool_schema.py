"""Build a JSON-schema-style tool dict from a Tool dataclass."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Tool

_EMPTY_PARAMETERS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def build_tool_schema(tool: Tool) -> dict[str, Any]:
    """Convert a Tool dataclass into a provider-compatible schema dict.

    Parameters
    ----------
    tool:
        Tool dataclass instance.

    Returns
    -------
    dict
        Dict with ``"name"``, ``"description"``, and ``"parameters"`` keys.
        When ``tool.parameters`` is falsy the default empty-object schema is
        used.

    Raises
    ------
    ValueError
        If ``tool.description`` is empty or whitespace-only.
    """
    if not tool.description or not tool.description.strip():
        raise ValueError(
            f"tool {tool.name!r} must have a non-empty description"
        )

    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters if tool.parameters else _EMPTY_PARAMETERS,
    }

"""Convert an McpToolSpec into an internal tool schema dict."""
from __future__ import annotations

from typing import Any

from ._hicode_types import McpToolSpec

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def mcp_tool_to_schema(spec: McpToolSpec) -> dict[str, Any]:
    """Return an internal tool schema for *spec*.

    The tool name is prefixed with ``"mcp_"`` to provide namespace isolation
    from built-in tools.

    Parameters
    ----------
    spec:
        MCP tool specification to convert.

    Returns
    -------
    dict
        ``{"name": "mcp_<spec.name>", "description": ..., "parameters": ...}``
    """
    return {
        "name": f"mcp_{spec.name}",
        "description": spec.description,
        "parameters": spec.input_schema or _EMPTY_SCHEMA,
    }

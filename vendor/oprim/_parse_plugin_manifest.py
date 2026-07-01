"""P-NEW4 parse_plugin_manifest — parse plugin.json manifest to PluginManifest."""
from __future__ import annotations

import json
from typing import Any

from oprim._cc_types import PluginManifest


def parse_plugin_manifest(raw: str) -> PluginManifest:
    """Parse *raw* JSON string to a PluginManifest.

    Args:
        raw: Raw plugin.json content (JSON string).

    Returns:
        PluginManifest with all fields populated.

    Raises:
        ValueError: If raw is not valid JSON or missing required fields.
    """
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid plugin manifest JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Plugin manifest must be a JSON object")

    name = data.get("name", "")
    if not name:
        raise ValueError("Plugin manifest missing required field: 'name'")

    version = data.get("version", "")
    if not version:
        raise ValueError("Plugin manifest missing required field: 'version'")

    return PluginManifest(
        name=str(name),
        version=str(version),
        skills=list(data.get("skills", [])),
        subagents=list(data.get("subagents", [])),
        commands=list(data.get("commands", [])),
        hooks=list(data.get("hooks", [])),
        mcp_defs=list(data.get("mcp_defs") or data.get("mcpDefs") or []),
        description=str(data.get("description", "")),
    )

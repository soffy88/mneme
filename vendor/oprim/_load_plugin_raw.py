"""P-NEW5 load_plugin_raw — read plugin.json from a plugin directory (IO only).

Does NOT parse the content. Parse with parse_plugin_manifest (P-NEW4).
Symmetrical to load_skill_raw / parse_skill_md pattern.
"""
from __future__ import annotations

from pathlib import Path

_MANIFEST_FILENAME = "plugin.json"


async def load_plugin_raw(path: Path) -> str:
    """Read the plugin.json manifest from *path* and return its raw content.

    Args:
        path: Plugin bundle directory path (must contain plugin.json).

    Returns:
        Raw string content of plugin.json (may be empty string).

    Raises:
        FileNotFoundError: If *path* does not exist or plugin.json is absent.
    """
    if not path.exists():
        raise FileNotFoundError(f"Plugin path does not exist: {path}")

    manifest_path = path / _MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"No plugin.json in: {path}")

    return manifest_path.read_text(encoding="utf-8")

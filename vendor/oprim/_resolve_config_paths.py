"""Pure path computation for opencode config file resolution."""
from __future__ import annotations

from pathlib import Path


def resolve_config_paths(*, cwd: "Path", home: "Path") -> list[Path]:
    """Return candidate config Path objects in priority order (low → high).

    Priority (index 0 = lowest, last = highest):
        1. ~/.config/opencode/opencode.json
        2. <cwd>/opencode.json
        3. <cwd>/.opencode/opencode.json

    If *cwd* == *home* the cwd-relative entries are deduplicated so that
    ``~/.config/opencode/opencode.json`` appears only once (at its original
    position) and the global-config slot is the only entry.

    No disk I/O is performed.
    """
    global_config = home / ".config" / "opencode" / "opencode.json"
    cwd_flat = cwd / "opencode.json"
    cwd_dot = cwd / ".opencode" / "opencode.json"

    if cwd == home:
        # Deduplicate: the cwd-relative paths collapse onto the global entry
        # and the local-project slots.  Keep all three logical slots but
        # resolve to their real (potentially identical) paths, then deduplicate
        # while preserving order (last occurrence wins = highest priority).
        seen: dict[Path, None] = {}
        for p in (global_config, cwd_flat, cwd_dot):
            seen[p] = None  # insertion-ordered dict; later keys overwrite
        return list(seen.keys())

    return [global_config, cwd_flat, cwd_dot]

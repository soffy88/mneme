"""Resolve relative and home-relative path strings in config dicts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_PATH_KEYS = frozenset({"working_dir", "cwd", "root", "output_dir"})


def _looks_like_path(value: str) -> bool:
    """Return True if *value* looks like a filesystem path.

    Heuristics:
    - Starts with ``~`` (home-relative)
    - Starts with ``/`` or a drive letter (absolute on POSIX/Windows)
    - Contains a path separator (``/`` or ``\\``)
    - Is a known path key value (caller handles key-based matching separately)
    """
    if not value:
        return False
    if value.startswith("~"):
        return True
    if value.startswith("/") or value.startswith("\\"):
        return True
    # Windows absolute: C:\... or C:/...
    if len(value) >= 3 and value[1] == ":" and value[2] in ("/", "\\"):
        return True
    if "/" in value or "\\" in value:
        return True
    return False


def _resolve_path_str(value: str, base: Path) -> str:
    """Resolve a single path string relative to *base*."""
    p = Path(value)
    if str(value).startswith("~"):
        return str(p.expanduser())
    if p.is_absolute():
        return str(p)
    return str(base / p)


def _resolve_value(value: Any, base: Path, *, in_path_key: bool = False) -> Any:
    if isinstance(value, str):
        if in_path_key or _looks_like_path(value):
            return _resolve_path_str(value, base)
        return value
    if isinstance(value, dict):
        return {
            k: _resolve_value(v, base, in_path_key=(k in _PATH_KEYS))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_resolve_value(item, base, in_path_key=in_path_key) for item in value]
    return value


def resolve_config_path_refs(config: dict[str, Any], *, base: "Path") -> dict[str, Any]:
    """Resolve path strings in *config* relative to *base*.

    Rules applied to string values:
    - Keys named ``working_dir``, ``cwd``, ``root``, or ``output_dir`` are
      always treated as paths.
    - Any string at any nesting level that *looks* like a path (contains a
      separator, starts with ``~``, etc.) is also resolved.
    - Relative paths → ``base / path``
    - ``~``-prefixed paths → expanded via :func:`pathlib.Path.expanduser`
    - Absolute paths pass through unchanged.

    Returns a new dict; *config* is not mutated.
    """
    return {
        k: _resolve_value(v, base, in_path_key=(k in _PATH_KEYS))
        for k, v in config.items()
    }

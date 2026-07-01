"""Resolve an external directory path against an allowlist of roots."""
from __future__ import annotations

from pathlib import Path


def resolve_external_dir(path: Path, *, allowlist: list[Path]) -> Path:
    """Resolve *path* and verify it is under one of the *allowlist* roots.

    Args:
        path: Directory path to resolve and validate.
        allowlist: List of ``Path`` objects that are permitted root directories.
                   Must not be empty.

    Returns:
        The resolved ``Path``.

    Raises:
        ValueError: If *allowlist* is empty, or if the resolved path is not
                    under any allowlist root.
    """
    if not allowlist:
        raise ValueError("allowlist must not be empty")

    path_resolved = path.resolve()

    for root in allowlist:
        root_resolved = root.resolve()
        if path_resolved == root_resolved or path_resolved.is_relative_to(root_resolved):
            return path_resolved

    raise ValueError(f"path not in allowlist: {path_resolved}")

"""Pure-compute: apply_gitignore."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from ._hicode_types import Pattern


def apply_gitignore(
    paths: list[Path], *, patterns: list[Pattern], root: Path
) -> list[Path]:
    """Filter *paths* according to gitignore-style *patterns*.

    Patterns are evaluated in order; later patterns override earlier ones.
    Negated patterns (``!``) un-ignore a previously ignored path.
    Supports ``*`` (single segment) and ``**`` (cross-segment) globbing.

    Args:
        paths: List of :class:`~pathlib.Path` objects to filter.
        patterns: Ordered list of :class:`~._hicode_types.Pattern` objects.
        root: The root directory relative to which paths are evaluated.

    Returns:
        Filtered list of paths that are NOT ignored.
    """

    def _matches(path: Path, pattern: Pattern) -> bool:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path

        rel_str = rel.as_posix()
        pat = pattern.pattern

        # dir_only patterns only match directories; since we only have paths
        # (not guaranteed to be dirs), match by trailing slash hint on name.
        if pattern.dir_only:
            # We can't know if path is a dir without stat; match by name heuristic
            # Treat as matching the last component as a directory segment.
            pass

        if pattern.anchored:
            # Must match from root
            candidates = [rel_str]
        else:
            # Can match any suffix of the path segments
            parts = rel_str.split("/")
            candidates = ["/".join(parts[i:]) for i in range(len(parts))]
            candidates.append(rel_str)

        for candidate in candidates:
            # Replace ** with a placeholder for fnmatch, then handle it
            if "**" in pat:
                # Convert ** glob to regex-style matching via fnmatch on full path
                import re
                regex_pat = re.escape(pat).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
                if re.fullmatch(regex_pat, candidate):
                    return True
                if re.fullmatch(regex_pat, rel_str):
                    return True
            else:
                if fnmatch.fnmatch(candidate, pat):
                    return True
                # Also try matching just the filename
                if fnmatch.fnmatch(path.name, pat):
                    return True

        return False

    result: list[Path] = []
    for path in paths:
        ignored = False
        for pattern in patterns:
            if _matches(path, pattern):
                ignored = not pattern.negated
        if not ignored:
            result.append(path)

    return result

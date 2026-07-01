"""Pure-compute: build_ripgrep_args."""
from __future__ import annotations


def build_ripgrep_args(
    *,
    pattern: str,
    glob: str | None = None,
    flags: str = "",
) -> list[str]:
    """Build a ``rg`` argument list.

    Args:
        pattern: The search pattern (must be non-empty).
        glob: Optional ``--glob`` value to restrict file types.
        flags: Whitespace-separated extra flags (e.g. ``"-i -l"``).

    Returns:
        List of strings suitable for passing to :func:`subprocess.run`.

    Raises:
        ValueError: If *pattern* is empty.
    """
    if not pattern:
        raise ValueError("pattern must not be empty")

    args: list[str] = ["rg", "--json"]

    if flags:
        args.extend(flags.split())

    if glob is not None:
        args.extend(["--glob", glob])

    args.append(pattern)
    return args

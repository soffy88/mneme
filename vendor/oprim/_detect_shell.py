"""Detect the default shell for a given platform string."""
from __future__ import annotations

_PLATFORM_MAP: dict[str, str] = {
    "linux": "bash",
    "darwin": "zsh",
    "win32": "pwsh",
}


def detect_shell(*, platform: str) -> str:
    """Return the default shell name for *platform*.

    Args:
        platform: A platform identifier such as ``"linux"``, ``"darwin"``,
            or ``"win32"``.  Must be a non-empty string.

    Returns:
        Shell executable name (``"bash"``, ``"zsh"``, ``"pwsh"``, or
        ``"sh"`` for unrecognised platforms).

    Raises:
        ValueError: If *platform* is an empty string.
    """
    if not platform:
        raise ValueError("platform must be a non-empty string")

    return _PLATFORM_MAP.get(platform, "sh")

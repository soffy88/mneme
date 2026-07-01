"""Sanitize an environment variable dict by removing sensitive keys."""
from __future__ import annotations

import re

_SENSITIVE_PATTERN = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE)


def sanitize_env(
    env: dict[str, str],
    *,
    allowlist: set[str] | None = None,
) -> dict[str, str]:
    """Return a filtered copy of *env* with sensitive entries removed.

    Args:
        env: Source environment mapping.
        allowlist: If provided, only keys present in this set are kept.
            When *None*, keys whose names contain ``KEY``, ``TOKEN``,
            ``SECRET``, or ``PASSWORD`` (case-insensitive) are dropped.

    Returns:
        A new dict; the original is never mutated.
    """
    if allowlist is not None:
        return {k: v for k, v in env.items() if k in allowlist}

    return {k: v for k, v in env.items() if not _SENSITIVE_PATTERN.search(k)}

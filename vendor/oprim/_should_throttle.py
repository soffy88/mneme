# oprim/oprim/should_throttle.py
from __future__ import annotations

from datetime import UTC, datetime


def should_throttle(
    *,
    last_fired_at: datetime | None,
    throttle_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Return True if current time is still within the throttle window (should skip).

    Args:
        last_fired_at: When the action last fired. None means never fired → allow (False).
        throttle_seconds: Window size in seconds. Must be > 0.
        now: Current time for testing. None → datetime.now(UTC).

    Returns:
        True: throttled (skip), False: not throttled (allow).

    Raises:
        ValueError: throttle_seconds <= 0, or naive datetime passed.
    """
    if throttle_seconds <= 0:
        raise ValueError(f"throttle_seconds must be > 0, got {throttle_seconds}")

    if last_fired_at is None:
        return False

    if now is None:
        now = datetime.now(UTC)

    if last_fired_at.tzinfo is None:
        raise ValueError("last_fired_at must be timezone-aware")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    elapsed_seconds = (now - last_fired_at).total_seconds()
    return elapsed_seconds < throttle_seconds

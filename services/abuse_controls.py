"""Small, explicit rate-limit contract for high-cost boundaries.

The auth service already applies Redis-backed verification throttling.  This
module centralizes the remaining route budgets so an adapter can enforce them
without every service inventing its own limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimit:
    scope: str
    requests: int
    window_seconds: int


RATE_LIMITS = {
    "login": RateLimit("user_or_ip", 10, 60),
    "upload": RateLimit("user", 10, 3600),
    "ai_tutor": RateLimit("user", 60, 3600),
    "learn_now": RateLimit("user", 120, 3600),
    "export": RateLimit("user", 3, 3600),
    "purge": RateLimit("user", 3, 86400),
    "analysis": RateLimit("operator", 10, 3600),
}


def rate_limit_for(operation: str) -> RateLimit:
    try:
        return RATE_LIMITS[operation]
    except KeyError as exc:
        raise ValueError(f"unknown rate-limited operation: {operation}") from exc


__all__ = ["RATE_LIMITS", "RateLimit", "rate_limit_for"]

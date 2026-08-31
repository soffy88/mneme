"""Bounded timeout policy shared by provider HTTP callers.

The policy is intentionally small and dependency-free until the timeout object
is requested.  Callers may tune the values through server-side environment
configuration, but hard upper bounds prevent a provider call from occupying a
worker for minutes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_CONNECT_SECONDS = 5.0
_DEFAULT_READ_SECONDS = 60.0
_MAX_CONNECT_SECONDS = 15.0
_MAX_READ_SECONDS = 120.0


def _bounded_float(name: str, default: float, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, maximum)


@dataclass(frozen=True, slots=True)
class ProviderTimeoutPolicy:
    connect_seconds: float
    read_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.connect_seconds + self.read_seconds


def provider_timeout_policy() -> ProviderTimeoutPolicy:
    """Read bounded server-side connect/read timeout settings."""

    return ProviderTimeoutPolicy(
        connect_seconds=_bounded_float(
            "MNEME_PROVIDER_CONNECT_TIMEOUT_SECONDS",
            _DEFAULT_CONNECT_SECONDS,
            _MAX_CONNECT_SECONDS,
        ),
        read_seconds=_bounded_float(
            "MNEME_PROVIDER_READ_TIMEOUT_SECONDS",
            _DEFAULT_READ_SECONDS,
            _MAX_READ_SECONDS,
        ),
    )


def provider_httpx_timeout():
    """Return an ``httpx.Timeout`` using the shared bounded policy."""

    import httpx

    policy = provider_timeout_policy()
    return httpx.Timeout(
        connect=policy.connect_seconds,
        read=policy.read_seconds,
        write=policy.read_seconds,
        pool=policy.connect_seconds,
    )


__all__ = ["ProviderTimeoutPolicy", "provider_httpx_timeout", "provider_timeout_policy"]

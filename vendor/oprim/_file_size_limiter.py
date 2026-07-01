"""Check if a file size is within the limit for the given client type."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

_MB = 1024 * 1024

_LIMITS: dict[str, int] = {
    "miniprogram": 20 * _MB,
    "official_account": 20 * _MB,
    "desktop": 500 * _MB,
    "web": 100 * _MB,
}

ClientType = Literal["miniprogram", "official_account", "desktop", "web"]


class SizeLimitResult(BaseModel):
    allowed: bool
    file_size: int
    limit: int
    client_type: str
    reason: str | None


def file_size_limiter(
    *,
    file_size: int,
    client_type: ClientType,
) -> SizeLimitResult:
    """Check if a file size is within the limit for the given client type.

    Limits:
        miniprogram: 20 MB
        official_account: 20 MB
        desktop: 500 MB
        web: 100 MB

    Args:
        file_size: File size in bytes
        client_type: Client platform type

    Returns:
        SizeLimitResult with allowed flag and limit info

    Raises:
        ValueError: file_size < 0

    Example:
        >>> result = file_size_limiter(file_size=1024, client_type="web")
        >>> result.allowed
        True
    """
    if file_size < 0:
        raise ValueError(f"file_size must be >= 0, got {file_size}")

    limit = _LIMITS[client_type]
    allowed = file_size <= limit
    reason = None if allowed else f"file_size {file_size} exceeds limit {limit} for {client_type}"

    return SizeLimitResult(
        allowed=allowed,
        file_size=file_size,
        limit=limit,
        client_type=client_type,
        reason=reason,
    )

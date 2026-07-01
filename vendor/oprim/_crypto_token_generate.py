"""Generate a cryptographically secure random token."""

from __future__ import annotations

import secrets


def crypto_token_generate(
    *,
    length: int = 32,
    url_safe: bool = True,
) -> str:
    """Generate a cryptographically secure random token.

    Uses secrets.token_urlsafe() for url_safe=True (base64url, [A-Za-z0-9_-]).
    Uses secrets.token_hex() for url_safe=False (hex string).

    Args:
        length: Number of random bytes. url_safe=True produces ceil(length*4/3) chars.
                length=32 → 43 chars (base64url).
        url_safe: If True, output is URL-safe base64 (default). If False, hex.

    Returns:
        Token string

    Raises:
        ValueError: length < 1

    Example:
        >>> token = crypto_token_generate()
        >>> len(token)
        43
    """
    if length < 1:
        raise ValueError(f"length must be >= 1, got {length}")

    if url_safe:
        return secrets.token_urlsafe(length)
    return secrets.token_hex(length)

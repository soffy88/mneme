"""SSRF pre-flight URL safety check oprim."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from pydantic import BaseModel

_CGN_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class URLSafetyResult(BaseModel):
    is_safe: bool
    reason: str | None
    resolved_ips: list[str]
    failed_check: str | None


class URLSafetyError(Exception):
    """Technical error (distinct from business rejection)."""


def url_safety_check(
    *,
    url: str,
    allowed_schemes: list[str] | None = None,
    block_loopback: bool = True,
    block_private: bool = True,
    block_link_local: bool = True,
    block_reserved: bool = True,
    block_multicast: bool = True,
) -> URLSafetyResult:
    """SSRF pre-flight URL safety check.

    Validation flow:
    1. urlparse → verify scheme is in the allow-list.
    2. socket.getaddrinfo → resolve all A/AAAA records (not just the first,
       to prevent multi-homed host bypass).
    3. For each resolved IP, test up to 5 attributes controlled by the
       ``block_*`` parameters.

    Args:
        url: URL to validate.
        allowed_schemes: Permitted schemes. Defaults to ``["http", "https"]``.
        block_loopback: Block loopback addresses (127.0.0.1, ::1, …).
        block_private: Block RFC 1918 private addresses.
        block_link_local: Block link-local addresses (169.254.x.x, fe80::, …).
        block_reserved: Block IANA-reserved addresses (wider than *block_private*,
            includes 100.64/10 CGN).
        block_multicast: Block multicast addresses.

    Returns:
        :class:`URLSafetyResult` with ``is_safe``, ``reason``,
        ``resolved_ips``, and ``failed_check``.

    Raises:
        URLSafetyError: Technical failure (URL parse crash, unexpected
            ``getaddrinfo`` error). Business rejections are returned as
            ``is_safe=False``, not raised.

    Note:
        A DNS-rebinding window exists between this check and the actual HTTP
        request. High-security callers should reuse ``resolved_ips`` from
        this result and bind the HTTP socket directly, rather than re-resolving.

        ``block_reserved`` is wider than ``block_private``: it additionally
        covers IANA special-purpose ranges such as 100.64/10 (CGN, RFC 6598).
        Both are enabled by default for maximum defence.

    Example:
        >>> result = url_safety_check(url="http://127.0.0.1")
        >>> result.is_safe
        False
        >>> result.failed_check
        'is_loopback'

        >>> result = url_safety_check(url="ftp://example.com")
        >>> result.reason
        'scheme_not_allowed'
    """
    if allowed_schemes is None:
        allowed_schemes = ["http", "https"]

    # 1. Parse + scheme check
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise URLSafetyError(f"url parse failed: {e}") from e

    if parsed.scheme not in allowed_schemes:
        return URLSafetyResult(
            is_safe=False,
            reason="scheme_not_allowed",
            resolved_ips=[],
            failed_check=None,
        )

    if not parsed.hostname:
        return URLSafetyResult(
            is_safe=False,
            reason="no_hostname",
            resolved_ips=[],
            failed_check=None,
        )

    # 2. Resolve all A/AAAA records
    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return URLSafetyResult(
            is_safe=False,
            reason="dns_resolution_failed",
            resolved_ips=[],
            failed_check=None,
        )
    except Exception as e:
        raise URLSafetyError(f"getaddrinfo unexpected error: {e}") from e

    resolved_ips: list[str] = []
    for _, _, _, _, sockaddr in addrinfo:
        try:
            resolved_ips.append(str(sockaddr[0]))
        except (IndexError, TypeError):
            continue

    if not resolved_ips:
        return URLSafetyResult(
            is_safe=False,
            reason="dns_resolution_failed",
            resolved_ips=[],
            failed_check=None,
        )

    # 3. Check each IP against enabled block attributes.
    # Order: link_local before private — 169.254/16 is both in Python 3.12,
    # and the more-specific link_local label is more informative.
    checks = [
        (block_loopback, "is_loopback"),
        (block_link_local, "is_link_local"),
        (block_private, "is_private"),
        (block_reserved, "is_reserved"),
        (block_multicast, "is_multicast"),
    ]

    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for enabled, attr in checks:
            if enabled and getattr(ip, attr):
                return URLSafetyResult(
                    is_safe=False,
                    reason=f"{attr}_blocked",
                    resolved_ips=resolved_ips,
                    failed_check=attr,
                )

        # CGN explicit check (block_reserved controls this too)
        if block_reserved and isinstance(ip, ipaddress.IPv4Address) and ip in _CGN_NETWORK:
            return URLSafetyResult(
                is_safe=False,
                reason="is_reserved_blocked",
                resolved_ips=resolved_ips,
                failed_check="is_reserved",
            )

    return URLSafetyResult(
        is_safe=True,
        reason=None,
        resolved_ips=resolved_ips,
        failed_check=None,
    )

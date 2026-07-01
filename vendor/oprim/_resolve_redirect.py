"""Resolve an HTTP redirect Location header relative to a base URL."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from ._validate_url import validate_url


def resolve_redirect(*, base_url: str, location: str) -> str:
    """Resolve a redirect *location* relative to *base_url*.

    Parameters
    ----------
    base_url:
        The URL of the original request (must be a valid HTTP/HTTPS URL).
    location:
        The value of the ``Location`` response header.

    Returns
    -------
    str
        The fully-resolved absolute URL.

    Raises
    ------
    ValueError
        If *location* is empty, or if *base_url* is not a valid HTTP/HTTPS URL.
    """
    if not location or not isinstance(location, str) or not location.strip():
        raise ValueError("location must be a non-empty string")

    if not validate_url(base_url):
        raise ValueError(f"base_url is not a valid HTTP/HTTPS URL: {base_url!r}")

    # Protocol-relative URL: inherit scheme from base_url
    if location.startswith("//"):
        scheme = urlparse(base_url).scheme
        location = f"{scheme}:{location}"

    # urljoin handles all remaining cases:
    #   - absolute URL  → returned as-is
    #   - relative path → joined with base_url
    return urljoin(base_url, location)

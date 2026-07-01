"""Validate whether a string is a well-formed HTTP/HTTPS URL."""

from __future__ import annotations

from urllib.parse import urlparse


def validate_url(url: str) -> bool:
    """Return ``True`` if *url* is a valid HTTP or HTTPS URL with a host.

    Parameters
    ----------
    url:
        The URL string to validate.

    Returns
    -------
    bool
        ``True`` when:

        * scheme is exactly ``"http"`` or ``"https"`` (case-insensitive after
          parsing),
        * a non-empty host is present,
        * there are no embedded spaces.

        ``False`` for empty strings, missing/wrong schemes (``file://``,
        ``ftp://``, bare paths, etc.) and URLs containing whitespace.
    """
    if not url or not isinstance(url, str):
        return False

    # Spaces anywhere in the URL are invalid
    if any(c in url for c in (" ", "\t", "\n", "\r")):
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False

    # urlparse requires a netloc/hostname for the URL to be meaningful
    if not parsed.netloc:
        return False

    return True

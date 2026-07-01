"""oprim.url_fetch_ssrf_safe — Fetch URL content with SSRF protection.

3O layer: oprim (single atomic HTTP fetch, DNS-pinned transport via obase).
Prevents SSRF via DNS pinning (obase.http.dns_pinned_transport).
"""

from __future__ import annotations

import urllib.request

from obase.http.dns_pinned_transport import SSRFBlockedError, make_ssrf_safe_opener


def url_fetch_ssrf_safe(
    *,
    url: str,
    timeout: int = 10,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    headers: dict[str, str] | None = None,
) -> dict:
    """Fetch URL content safely, blocking requests to private/internal IPs.

    Returns: {url, status_code, content_type, body_bytes, body_text, error}
    On SSRF block: error is set, body_bytes is empty.
    """
    result: dict = {
        "url": url,
        "status_code": None,
        "content_type": None,
        "body_bytes": b"",
        "body_text": None,
        "error": None,
    }

    try:
        opener = make_ssrf_safe_opener(timeout=timeout)
        req = urllib.request.Request(url, headers=headers or {})
        with opener.open(req, timeout=timeout) as resp:
            result["status_code"] = resp.status
            result["content_type"] = resp.headers.get("Content-Type")
            body = resp.read(max_bytes)
            result["body_bytes"] = body
            try:
                result["body_text"] = body.decode("utf-8", errors="replace")
            except Exception:
                result["body_text"] = None
    except SSRFBlockedError:
        result["error"] = "ssrf_blocked"
    except Exception as exc:
        result["error"] = str(exc)

    return result

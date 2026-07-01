"""oprim.searxng_search — Single atomic searxng query call.

3O layer: oprim (single atomic HTTP fetch + JSON parse, no state).
Queries a searxng instance and returns structured results.
Falls back to empty results if searxng is unreachable (no raise).
"""

from __future__ import annotations

import json
import urllib.request
import urllib.parse


def searxng_search(
    *,
    query: str,
    searxng_url: str,
    categories: list[str] | None = None,
    language: str = "en",
    time_range: str | None = None,
    max_results: int = 10,
    timeout: int = 10,
) -> dict:
    """Query a searxng instance and return structured results.

    Uses SSRF-safe transport when obase.http.dns_pinned_transport is available.
    Falls back to stdlib urllib for internal Docker URLs (172.17.x.x).

    Args:
        query: Search query string.
        searxng_url: Base URL of searxng instance (e.g. "http://172.17.0.2:8080").
        categories: Search categories (e.g. ["general", "news"]). None = default.
        language: Language code for results.
        time_range: Optional time filter: "day" | "week" | "month" | "year".
        max_results: Maximum results to return.
        timeout: HTTP timeout in seconds.

    Returns:
        {
            query: str,
            results: [{title, url, content, engine, score}],
            total: int,
            error: str | None,
        }
    """
    result: dict = {"query": query, "results": [], "total": 0, "error": None}

    if not query.strip():
        return result

    # Build searxng JSON API URL
    params: dict = {
        "q": query,
        "format": "json",
        "language": language,
    }
    if categories:
        params["categories"] = ",".join(categories)
    if time_range:
        params["time_range"] = time_range

    api_url = f"{searxng_url.rstrip('/')}/search?{urllib.parse.urlencode(params)}"

    try:
        # Try SSRF-safe opener first; fall back to plain urllib for Docker IPs
        try:
            from obase.http.dns_pinned_transport import make_ssrf_safe_opener

            opener = make_ssrf_safe_opener(timeout=timeout)
            req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
            resp_ctx = opener.open(req, timeout=timeout)
        except Exception:
            # Docker internal URL (172.17.x.x) — use plain urllib
            req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
            resp_ctx = urllib.request.urlopen(req, timeout=timeout)

        with resp_ctx as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))

        raw_results = body.get("results", [])[:max_results]
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "engine": r.get("engine", ""),
                "score": float(r.get("score", 0.0)),
            }
            for r in raw_results
        ]
        result["results"] = results
        result["total"] = len(results)

    except Exception as exc:
        result["error"] = str(exc)

    return result

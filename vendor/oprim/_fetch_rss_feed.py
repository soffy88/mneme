"""oprim.fetch_rss_feed — Fetch and parse an RSS 2.0 feed.

3O layer: oprim (single atomic feed fetch + parse).
Uses feedparser if available, falls back to defusedxml for safe XML parsing.
"""

from __future__ import annotations

import urllib.request
from urllib.parse import urlparse


def fetch_rss_feed(
    *,
    url: str,
    timeout: int = 10,
    max_items: int = 100,
) -> dict:
    """Fetch and parse RSS 2.0 feed from URL.

    Uses DNS-pinned SSRF-safe transport (obase.http.dns_pinned_transport).
    Only http/https schemes are allowed.

    Returns: {feed_title, feed_url, items: [{title, link, description, pub_date, guid}],
              item_count, error}
    """
    result: dict = {
        "feed_title": None,
        "feed_url": url,
        "items": [],
        "item_count": 0,
        "error": None,
    }

    # Restrict to http/https — reject file://, ftp://, etc.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        result["error"] = f"unsupported_scheme: {parsed.scheme!r}"
        return result

    try:
        from obase.http.dns_pinned_transport import SSRFBlockedError, make_ssrf_safe_opener

        opener = make_ssrf_safe_opener(timeout=timeout)
        req = urllib.request.Request(url)
        with opener.open(req, timeout=timeout) as resp:
            xml_bytes = resp.read()
        xml_string = xml_bytes.decode("utf-8", errors="replace")
    except Exception as exc:  # includes SSRFBlockedError
        from obase.http.dns_pinned_transport import SSRFBlockedError as _SSRFBlockedError

        if isinstance(exc, _SSRFBlockedError):
            result["error"] = f"ssrf_blocked: {exc}"
        else:
            result["error"] = str(exc)
        return result

    return _parse_rss_xml(xml_string=xml_string, feed_url=url, max_items=max_items)


def _parse_rss_xml(*, xml_string: str, feed_url: str, max_items: int) -> dict:
    """Parse RSS 2.0 XML string and return structured dict."""
    result: dict = {
        "feed_title": None,
        "feed_url": feed_url,
        "items": [],
        "item_count": 0,
        "error": None,
    }

    # Try feedparser first
    try:
        import feedparser  # type: ignore

        parsed = feedparser.parse(xml_string)
        result["feed_title"] = parsed.feed.get("title")
        items = []
        for entry in parsed.entries[:max_items]:
            items.append(
                {
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "description": entry.get("summary"),
                    "pub_date": entry.get("published"),
                    "guid": entry.get("id"),
                }
            )
        result["items"] = items
        result["item_count"] = len(items)
        return result
    except ImportError:
        pass
    except Exception as exc:
        result["error"] = str(exc)
        return result

    # defusedxml fallback — prevents XXE / billion-laughs attacks
    try:
        import defusedxml.ElementTree as ET  # type: ignore

        root = ET.fromstring(xml_string)
        channel = root.find("channel")
        if channel is None:
            channel = root

        title_el = channel.find("title")
        result["feed_title"] = title_el.text if title_el is not None else None

        items = []
        for item_el in channel.findall("item")[:max_items]:

            def _text(tag: str, _el=item_el) -> str | None:
                el = _el.find(tag)
                return el.text if el is not None else None

            items.append(
                {
                    "title": _text("title"),
                    "link": _text("link"),
                    "description": _text("description"),
                    "pub_date": _text("pubDate"),
                    "guid": _text("guid"),
                }
            )
        result["items"] = items
        result["item_count"] = len(items)
    except Exception as exc:
        result["error"] = f"xml_parse_error: {exc}"

    return result

"""oprim.detect_feed_url — Detect RSS/Atom feed URL from a webpage's HTML.

3O layer: oprim (single atomic HTML parse, no HTTP).
Finds <link rel="alternate" type="application/rss+xml"> and similar tags.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

_FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/feed+json",
}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attr = dict(attrs)
        rel = (attr.get("rel") or "").lower()
        mime = (attr.get("type") or "").lower().strip()
        if "alternate" not in rel:
            return
        if mime not in _FEED_TYPES:
            return
        href = attr.get("href") or ""
        if not href:
            return
        self.feeds.append(
            {
                "url": href,
                "type": mime,
                "title": attr.get("title") or None,
            }
        )


def detect_feed_url(
    *,
    html: str,
    base_url: str = "",
) -> dict:
    """Detect feed URLs from HTML <link> tags.

    Returns: {feeds: [{url, type, title}], primary_feed: str|None, error}
    primary_feed: the first/best RSS or Atom feed URL found.
    """
    result: dict = {
        "feeds": [],
        "primary_feed": None,
        "error": None,
    }

    try:
        parser = _LinkParser()
        parser.feed(html)
    except Exception as exc:
        result["error"] = str(exc)
        return result

    feeds = []
    for item in parser.feeds:
        url = item["url"]
        if base_url:
            url = urljoin(base_url, url)
        feeds.append({"url": url, "type": item["type"], "title": item["title"]})

    result["feeds"] = feeds
    result["primary_feed"] = feeds[0]["url"] if feeds else None
    return result

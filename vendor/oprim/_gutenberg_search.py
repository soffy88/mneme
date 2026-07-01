"""Project Gutenberg book search via Gutendex public API."""
from __future__ import annotations

import time
import urllib.request
import urllib.parse
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def gutenberg_search(
    *,
    topic: str | None = None,
    languages: list[str] | None = None,
    keywords: str | None = None,
    author: str | None = None,
    max_results: int = 10,
    rate_limit_sleep: float = 1.0,
) -> list:
    """Search Project Gutenberg via Gutendex API.

    Returns list[SourceResult] with epub/txt download URLs.
    """
    from oprim._media_types import SourceResult

    if rate_limit_sleep > 0:
        time.sleep(rate_limit_sleep)

    params: dict[str, str] = {}
    search_parts: list[str] = []
    if topic:
        search_parts.append(topic)
    if keywords:
        search_parts.append(keywords)
    if author:
        search_parts.append(author)
    if search_parts:
        params["search"] = " ".join(search_parts)
    if topic and not search_parts:
        params["topic"] = topic
    if languages:
        params["languages"] = ",".join(languages)

    url = "https://gutendex.com/books/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "oprim/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    results: list[SourceResult] = []
    for book in data.get("results", [])[:max_results]:
        book_id = str(book.get("id", ""))
        title = (book.get("title") or "").strip()
        if not book_id or not title:
            continue

        formats: dict = book.get("formats") or {}
        txt_url = (
            formats.get("text/plain; charset=utf-8")
            or formats.get("text/plain")
        )
        epub_url = formats.get("application/epub+zip") or formats.get("application/epub")
        # Prefer txt: epub bundle ingestion requires oskill v2+ content_override support
        if txt_url:
            dl_url, file_type = txt_url, "txt"
        elif epub_url:
            dl_url, file_type = epub_url, "epub"
        else:
            continue  # no downloadable format

        authors = [
            a.get("name", "") for a in (book.get("authors") or []) if a.get("name")
        ]
        subjects = (book.get("subjects") or [])[:10]
        results.append(
            SourceResult(
                external_id=book_id,
                title=title,
                download_url=dl_url,
                file_type=file_type,
                metadata={
                    "authors": authors,
                    "subjects": subjects,
                    "download_count": book.get("download_count", 0),
                    "gutenberg_id": book_id,
                    "source_type": "gutenberg",
                },
            )
        )

    return results

"""oskill.feed_diff_pipeline — Multi-feed monitoring with change detection.

3O layer: oskill (≥2 oprim composition, stateless).

Internal oprim composition:
    - oprim.fetch_rss_feed: fetch RSS 2.0 feeds
    - oprim.parse_atom_feed: parse Atom format feeds
    - oprim.feed_diff_detector: detect new/removed items between snapshots
"""

from __future__ import annotations

from oprim import feed_diff_detector, fetch_rss_feed, parse_atom_feed


def feed_diff_pipeline(
    *,
    feed_url: str,
    previous_items: list[dict] | None = None,
    feed_format: str = "auto",  # "rss" | "atom" | "auto"
    timeout: int = 10,
    max_items: int = 100,
) -> dict:
    """Fetch a feed, compare to previous snapshot, return only new items.

    Fetches the feed at feed_url using RSS or Atom parsing depending on
    feed_format. Compares freshly fetched items against previous_items
    snapshot via feed_diff_detector. Returns new, removed, and all items.

    Internal oprim composition:
        fetch_rss_feed handles RSS 2.0 fetch + parse.
        parse_atom_feed handles Atom 1.0 XML parse (requires pre-fetched XML).
        feed_diff_detector computes added/removed sets between snapshots.

    Returns: {
        new_items: list[dict],
        removed_items: list[dict],
        all_items: list[dict],
        feed_title: str | None,
        total_new: int,
        error: str | None,
    }
    """
    result: dict = {
        "new_items": [],
        "removed_items": [],
        "all_items": [],
        "feed_title": None,
        "total_new": 0,
        "error": None,
    }

    if previous_items is None:
        previous_items = []

    # 1. Fetch + parse feed
    fetched_items: list[dict] = []
    feed_title: str | None = None

    if feed_format == "atom":
        # Atom path: fetch raw XML then parse via parse_atom_feed
        try:
            import urllib.request

            with urllib.request.urlopen(feed_url, timeout=timeout) as resp:
                xml_bytes = resp.read()
            xml_str = xml_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            result["error"] = str(exc)
            return result

        atom_result = parse_atom_feed(xml=xml_str, max_items=max_items)
        if atom_result.get("error"):
            result["error"] = atom_result["error"]
            return result
        # Normalise Atom entries to common schema
        for entry in atom_result.get("items", []):
            fetched_items.append(
                {
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "description": entry.get("summary"),
                    "pub_date": entry.get("updated"),
                    "guid": entry.get("id"),
                }
            )
        feed_title = atom_result.get("feed_title")

    else:
        # RSS path (default / "rss" / "auto")
        rss_result = fetch_rss_feed(url=feed_url, timeout=timeout, max_items=max_items)
        if rss_result.get("error"):
            # "auto" mode: record error but still return empty diff
            result["error"] = rss_result["error"]
            return result
        fetched_items = rss_result.get("items", [])
        feed_title = rss_result.get("feed_title")

    result["all_items"] = fetched_items
    result["feed_title"] = feed_title

    # 2. Diff via feed_diff_detector
    diff = feed_diff_detector(old_items=previous_items, new_items=fetched_items)
    result["new_items"] = diff["new_items"]
    result["removed_items"] = diff["removed_items"]
    result["total_new"] = diff["total_new"]

    return result

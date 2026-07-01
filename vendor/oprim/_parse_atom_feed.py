"""oprim.parse_atom_feed — Parse an Atom feed from XML string or URL content.

3O layer: oprim (single atomic Atom XML parse, no HTTP).
Handles Atom 1.0 format independently of RSS.
"""

from __future__ import annotations

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def parse_atom_feed(
    *,
    xml: str,
    max_items: int = 100,
) -> dict:
    """Parse Atom 1.0 feed XML string.

    Returns: {feed_title, feed_id, updated, items: [{title, id, link, summary, updated, author}],
              item_count, error}
    """
    result: dict = {
        "feed_title": None,
        "feed_id": None,
        "updated": None,
        "items": [],
        "item_count": 0,
        "error": None,
    }

    try:
        import defusedxml.ElementTree as ET  # type: ignore

        root = ET.fromstring(xml)
    except Exception as exc:
        result["error"] = f"xml_parse_error: {exc}"
        return result

    def _t(el, tag: str) -> str | None:
        child = el.find(f"{_ATOM_NS}{tag}")
        return child.text if child is not None else None

    def _link(el) -> str | None:
        child = el.find(f"{_ATOM_NS}link")
        if child is None:
            return None
        return child.get("href") or child.text

    def _author(el) -> str | None:
        author_el = el.find(f"{_ATOM_NS}author")
        if author_el is None:
            return None
        name_el = author_el.find(f"{_ATOM_NS}name")
        return name_el.text if name_el is not None else None

    result["feed_title"] = _t(root, "title")
    result["feed_id"] = _t(root, "id")
    result["updated"] = _t(root, "updated")

    items = []
    for entry in root.findall(f"{_ATOM_NS}entry")[:max_items]:
        items.append(
            {
                "title": _t(entry, "title"),
                "id": _t(entry, "id"),
                "link": _link(entry),
                "summary": _t(entry, "summary"),
                "updated": _t(entry, "updated"),
                "author": _author(entry),
            }
        )
    result["items"] = items
    result["item_count"] = len(items)
    return result

"""oprim.feed_diff_detector — Detect new items between two feed fetches.

3O layer: oprim (single atomic diff, pure logic, no HTTP).
Compares two item lists by GUID/link, returns only new items.
"""

from __future__ import annotations


def feed_diff_detector(
    *,
    old_items: list[dict],
    new_items: list[dict],
    key_field: str = "guid",
) -> dict:
    """Compare two feed item snapshots, return new/removed items.

    Returns: {new_items: list, removed_items: list, unchanged_count: int, total_new: int}
    Uses key_field (default "guid", fallback "link") for deduplication.
    """

    def _key(item: dict) -> str | None:
        val = item.get(key_field)
        if val:
            return str(val)
        # fallback to "link" when primary key_field is absent
        fallback = item.get("link")
        return str(fallback) if fallback else None

    old_keys: set[str] = {k for item in old_items if (k := _key(item)) is not None}
    new_keys: set[str] = {k for item in new_items if (k := _key(item)) is not None}

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    unchanged_keys = old_keys & new_keys

    added_items = [item for item in new_items if _key(item) in added_keys]
    removed_items = [item for item in old_items if _key(item) in removed_keys]

    return {
        "new_items": added_items,
        "removed_items": removed_items,
        "unchanged_count": len(unchanged_keys),
        "total_new": len(added_items),
    }

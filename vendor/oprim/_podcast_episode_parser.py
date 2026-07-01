"""oprim.podcast_episode_parser — Parse podcast episodes from RSS XML (iTunes/enclosure).

3O layer: oprim (single atomic podcast RSS parse, no HTTP).
Handles iTunes podcast extensions: enclosure, duration, explicit, image.
"""

from __future__ import annotations

_ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def podcast_episode_parser(
    *,
    xml: str,
    max_episodes: int = 50,
) -> dict:
    """Parse podcast RSS feed, extracting episodes with audio enclosures.

    Returns: {
        podcast_title, podcast_author, podcast_description,
        episodes: [{title, link, pub_date, duration, enclosure_url, enclosure_type,
                    enclosure_length, guid}],
        episode_count, error
    }
    """
    result: dict = {
        "podcast_title": None,
        "podcast_author": None,
        "podcast_description": None,
        "episodes": [],
        "episode_count": 0,
        "error": None,
    }

    try:
        import defusedxml.ElementTree as ET  # type: ignore

        root = ET.fromstring(xml)
    except Exception as exc:
        result["error"] = f"xml_parse_error: {exc}"
        return result

    channel = root.find("channel")
    if channel is None:
        channel = root

    def _text(el, tag: str) -> str | None:
        child = el.find(tag)
        return child.text if child is not None else None

    result["podcast_title"] = _text(channel, "title")
    result["podcast_description"] = _text(channel, "description")
    result["podcast_author"] = _text(channel, f"{_ITUNES_NS}author") or _text(
        channel, "managingEditor"
    )

    episodes = []
    for item in channel.findall("item")[:max_episodes]:
        enclosure_el = item.find("enclosure")
        enclosure_url = None
        enclosure_type = None
        enclosure_length = None
        if enclosure_el is not None:
            enclosure_url = enclosure_el.get("url")
            enclosure_type = enclosure_el.get("type")
            raw_len = enclosure_el.get("length")
            if raw_len is not None:
                try:
                    enclosure_length = int(raw_len)
                except ValueError:
                    enclosure_length = None

        duration = _text(item, f"{_ITUNES_NS}duration") or _text(item, "duration")

        episodes.append(
            {
                "title": _text(item, "title"),
                "link": _text(item, "link"),
                "pub_date": _text(item, "pubDate"),
                "duration": duration,
                "enclosure_url": enclosure_url,
                "enclosure_type": enclosure_type,
                "enclosure_length": enclosure_length,
                "guid": _text(item, "guid"),
            }
        )

    result["episodes"] = episodes
    result["episode_count"] = len(episodes)
    return result

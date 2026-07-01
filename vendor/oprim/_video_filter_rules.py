"""P-4: video_filter_rules — pure-rule deterministic video filter."""
from __future__ import annotations

import re

from oprim._media_types import VideoMeta

_DATE_RE = re.compile(r"^\d{8}$")


def video_filter_rules(
    videos: list[VideoMeta],
    *,
    after_date: str | None = None,
    limit: int | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    title_include: list[str] | None = None,
    title_exclude: list[str] | None = None,
) -> list[VideoMeta]:
    """Filter and sort a list of VideoMeta by pure rules (no LLM).

    Filtering order:
    1. after_date — keep videos with upload_date >= after_date (YYYYMMDD).
    2. min_duration / max_duration — keep videos within duration range.
    3. title_include — all listed keywords must appear in title (case-insensitive).
    4. title_exclude — any listed keyword in title excludes the video.
    5. Sort remaining by upload_date descending (None dates sort last).
    6. limit — keep the first N after sorting.

    Args:
        videos: Input list.
        after_date: Earliest upload_date to include (YYYYMMDD string).
        limit: Maximum number of results after sorting.
        min_duration: Minimum video duration in seconds (inclusive).
        max_duration: Maximum video duration in seconds (inclusive).
        title_include: Keywords that must ALL appear in title.
        title_exclude: Keywords where ANY match excludes the video.

    Returns:
        Filtered (and limited) list of VideoMeta.

    Raises:
        ValueError: after_date is not in YYYYMMDD format.
        ValueError: limit is negative.
    """
    if not videos:
        return []

    if after_date is not None and not _DATE_RE.match(after_date):
        raise ValueError(f"after_date must be YYYYMMDD, got: {after_date!r}")

    if limit is not None and limit < 0:
        raise ValueError(f"limit must be non-negative, got: {limit}")

    result = list(videos)

    # 1. after_date filter
    if after_date is not None:
        result = [v for v in result if v.upload_date is not None and v.upload_date >= after_date]

    # 2. Duration filters
    if min_duration is not None:
        result = [v for v in result if v.duration >= min_duration]
    if max_duration is not None:
        result = [v for v in result if v.duration <= max_duration]

    # 3. title_include
    if title_include:
        for kw in title_include:
            kw_lower = kw.lower()
            result = [v for v in result if kw_lower in v.title.lower()]

    # 4. title_exclude
    if title_exclude:
        for kw in title_exclude:
            kw_lower = kw.lower()
            result = [v for v in result if kw_lower not in v.title.lower()]

    # 5. Sort by upload_date descending (None last)
    result.sort(key=lambda v: v.upload_date or "", reverse=True)

    # 6. limit
    if limit == 0:
        return []
    if limit is not None:
        result = result[:limit]

    return result

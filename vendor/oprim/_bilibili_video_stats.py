"""oprim.bilibili_video_stats — Fetch Bilibili video statistics.

Example:
    >>> from oprim.bilibili_video_stats import bilibili_video_stats
    >>> stats = await bilibili_video_stats(bvid="BV1xx", cookies={"SESSDATA": "x"})

Raises:
    BilibiliStatsError: Fetch failed.
"""

from __future__ import annotations

from oprim._providers.bilibili_api import BilibiliAPIError, BiliVideoStats


class BilibiliStatsError(Exception):
    """Bilibili stats fetch failed."""


async def bilibili_video_stats(*, bvid: str, cookies: dict[str, str]) -> BiliVideoStats:
    """Fetch Bilibili video statistics.

    Args:
        bvid: Bilibili video BV ID.
        cookies: Session cookies dict.

    Returns:
        BiliVideoStats model.

    Raises:
        BilibiliStatsError: API failure or cookies invalid.

    Example:
        >>> stats = await bilibili_video_stats(bvid="BV1xx", cookies={})
    """
    from oprim._providers.bilibili_api import video_stats

    try:
        return await video_stats(bvid=bvid, cookies=cookies)
    except BilibiliAPIError as exc:
        raise BilibiliStatsError(str(exc)) from exc

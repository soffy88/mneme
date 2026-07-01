"""oprim.bilibili_comments_fetch — Fetch Bilibili comments with pagination.

Example:
    >>> from oprim.bilibili_comments_fetch import bilibili_comments_fetch
    >>> comments = await bilibili_comments_fetch(bvid="BV1xx", cookies={"SESSDATA": "x"})

Raises:
    BilibiliCommentsError: Fetch failed.
"""

from __future__ import annotations

from oprim._providers.bilibili_api import BilibiliAPIError, BiliComment


class BilibiliCommentsError(Exception):
    """Bilibili comments fetch failed."""


async def bilibili_comments_fetch(
    *, bvid: str, cookies: dict[str, str], max_count: int = 100
) -> list[BiliComment]:
    """Fetch Bilibili comments with auto-pagination up to max_count.

    Args:
        bvid: Bilibili video BV ID.
        cookies: Session cookies dict.
        max_count: Maximum comments to fetch.

    Returns:
        List of BiliComment models.

    Raises:
        BilibiliCommentsError: API failure.

    Example:
        >>> comments = await bilibili_comments_fetch(bvid="BV1xx", cookies={})
    """
    from oprim._providers.bilibili_api import video_comments

    all_comments: list[BiliComment] = []
    page = 1

    try:
        while len(all_comments) < max_count:
            result = await video_comments(
                bvid=bvid, cookies=cookies, max_count=max_count, page=page,
            )
            all_comments.extend(result.comments)
            if not result.has_next:
                break
            page += 1
    except BilibiliAPIError as exc:
        raise BilibiliCommentsError(str(exc)) from exc

    return all_comments[:max_count]

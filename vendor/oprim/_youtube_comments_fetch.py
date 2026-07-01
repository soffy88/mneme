"""oprim.youtube_comments_fetch — Fetch YouTube comments with auto-pagination.

Example:
    >>> from oprim.youtube_comments_fetch import youtube_comments_fetch
    >>> comments = await youtube_comments_fetch(video_id="abc", oauth_token="tok")

Raises:
    YouTubeCommentsError: Fetch failed.
"""

from __future__ import annotations

from oprim._providers.youtube_api import (
    Comment,
    YouTubeAPIError,
    YouTubeAuthError,
)


class YouTubeCommentsError(Exception):
    """YouTube comments fetch failed."""


async def youtube_comments_fetch(
    *, video_id: str, oauth_token: str, max_count: int = 100
) -> list[Comment]:
    """Fetch YouTube comments with auto-pagination up to max_count.

    Args:
        video_id: YouTube video ID.
        oauth_token: OAuth2 bearer token.
        max_count: Maximum comments to fetch.

    Returns:
        List of Comment models.

    Raises:
        YouTubeCommentsError: Auth failure or API error.

    Example:
        >>> comments = await youtube_comments_fetch(video_id="x", oauth_token="t")
    """
    from oprim._providers.youtube_api import video_comments

    all_comments: list[Comment] = []
    page_token: str | None = None

    try:
        while len(all_comments) < max_count:
            page = await video_comments(
                video_id=video_id,
                oauth_token=oauth_token,
                max_count=min(100, max_count - len(all_comments)),
                page_token=page_token,
            )
            all_comments.extend(page.comments)
            if not page.next_page_token:
                break
            page_token = page.next_page_token
    except (YouTubeAuthError, YouTubeAPIError) as exc:
        raise YouTubeCommentsError(str(exc)) from exc

    return all_comments[:max_count]

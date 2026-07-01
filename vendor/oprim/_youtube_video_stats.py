"""oprim.youtube_video_stats — Fetch YouTube video statistics.

Example:
    >>> from oprim.youtube_video_stats import youtube_video_stats
    >>> stats = await youtube_video_stats(video_id="abc123", oauth_token="tok")

Raises:
    YouTubeStatsError: Fetch failed.
"""

from __future__ import annotations

from oprim._providers.youtube_api import (
    VideoStats,
    YouTubeAPIError,
    YouTubeAuthError,
)


class YouTubeStatsError(Exception):
    """YouTube stats fetch failed."""


async def youtube_video_stats(*, video_id: str, oauth_token: str) -> VideoStats:
    """Fetch YouTube video statistics.

    Args:
        video_id: YouTube video ID.
        oauth_token: OAuth2 bearer token.

    Returns:
        VideoStats model.

    Raises:
        YouTubeStatsError: Video not found, auth failure, or API error.

    Example:
        >>> stats = await youtube_video_stats(video_id="x", oauth_token="t")
    """
    from oprim._providers.youtube_api import video_stats

    try:
        return await video_stats(video_id=video_id, oauth_token=oauth_token)
    except (YouTubeAuthError, YouTubeAPIError) as exc:
        raise YouTubeStatsError(str(exc)) from exc

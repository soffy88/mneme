"""oprim._providers.youtube_api — YouTube Data API v3 wrapper."""

from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel


class YouTubeAPIError(Exception):
    """YouTube API call failed."""


class YouTubeAuthError(YouTubeAPIError):
    """OAuth token invalid or expired."""


class VideoStats(BaseModel):
    """YouTube video statistics."""

    video_id: str
    views: int
    likes: int
    dislikes: int | None = None
    comments_count: int
    duration_s: float


class Comment(BaseModel):
    """Single YouTube comment."""

    comment_id: str
    author: str
    text: str
    published_at: datetime
    likes: int


class CommentsPage(BaseModel):
    """Paginated comments response."""

    comments: list[Comment]
    next_page_token: str | None = None


class ChannelAnalytics(BaseModel):
    """Channel-level analytics."""

    views: int
    avg_view_duration_s: float
    completion_rate: float | None = None


_BASE = "https://www.googleapis.com/youtube/v3"


async def video_stats(*, video_id: str, oauth_token: str) -> VideoStats:
    """Fetch video statistics.

    Raises:
        YouTubeAuthError: Token invalid.
        YouTubeAPIError: API failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/videos",
            params={"id": video_id, "part": "statistics,contentDetails"},
            headers={"Authorization": f"Bearer {oauth_token}"},
        )
    if resp.status_code == 401:
        raise YouTubeAuthError("OAuth token invalid")
    if resp.status_code == 429:
        raise YouTubeAPIError("Rate limited (429)")
    if resp.status_code != 200:
        raise YouTubeAPIError(f"API error {resp.status_code}: {resp.text[:200]}")

    items = resp.json().get("items", [])
    if not items:
        raise YouTubeAPIError(f"Video not found: {video_id}")

    item = items[0]
    stats = item["statistics"]
    duration_iso = item["contentDetails"]["duration"]
    return VideoStats(
        video_id=video_id,
        views=int(stats.get("viewCount", 0)),
        likes=int(stats.get("likeCount", 0)),
        dislikes=int(stats.get("dislikeCount", 0)) if "dislikeCount" in stats else None,
        comments_count=int(stats.get("commentCount", 0)),
        duration_s=_parse_iso_duration(duration_iso),
    )


async def video_comments(
    *, video_id: str, oauth_token: str, max_count: int = 100, page_token: str | None = None
) -> CommentsPage:
    """Fetch video comments (one page).

    Raises:
        YouTubeAuthError: Token invalid.
        YouTubeAPIError: API failure.
    """
    params: dict[str, str | int] = {
        "videoId": video_id,
        "part": "snippet",
        "maxResults": min(max_count, 100),
        "order": "relevance",
    }
    if page_token:
        params["pageToken"] = page_token

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/commentThreads",
            params=params,
            headers={"Authorization": f"Bearer {oauth_token}"},
        )
    if resp.status_code == 401:
        raise YouTubeAuthError("OAuth token invalid")
    if resp.status_code != 200:
        raise YouTubeAPIError(f"Comments API error {resp.status_code}")

    data = resp.json()
    comments = []
    for item in data.get("items", []):
        snip = item["snippet"]["topLevelComment"]["snippet"]
        comments.append(Comment(
            comment_id=item["id"],
            author=snip["authorDisplayName"],
            text=snip["textDisplay"],
            published_at=datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00")),
            likes=snip.get("likeCount", 0),
        ))
    return CommentsPage(comments=comments, next_page_token=data.get("nextPageToken"))


async def channel_analytics(
    *,
    channel_id: str,
    oauth_token: str,
    since: datetime,
    until: datetime,
    metrics: list[str] | None = None,
) -> ChannelAnalytics:
    """Fetch channel analytics (YouTube Analytics API).

    Raises:
        YouTubeAuthError: Token invalid.
        YouTubeAPIError: API failure.
    """
    _metrics = metrics or ["views", "averageViewDuration"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids": f"channel=={channel_id}",
                "startDate": since.strftime("%Y-%m-%d"),
                "endDate": until.strftime("%Y-%m-%d"),
                "metrics": ",".join(_metrics),
            },
            headers={"Authorization": f"Bearer {oauth_token}"},
        )
    if resp.status_code == 401:
        raise YouTubeAuthError("OAuth token invalid")
    if resp.status_code != 200:
        raise YouTubeAPIError(f"Analytics API error {resp.status_code}")

    rows = resp.json().get("rows", [[0, 0]])
    row = rows[0] if rows else [0, 0]
    return ChannelAnalytics(
        views=int(row[0]) if len(row) > 0 else 0,
        avg_view_duration_s=float(row[1]) if len(row) > 1 else 0.0,
    )


def _parse_iso_duration(iso: str) -> float:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    import re

    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0.0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return float(h * 3600 + mi * 60 + s)

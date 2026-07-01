"""oprim._providers.bilibili_api — Bilibili API wrapper."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pydantic import BaseModel


class BilibiliAPIError(Exception):
    """Bilibili API call failed."""


class BiliVideoStats(BaseModel):
    """Bilibili video statistics."""

    bvid: str
    views: int
    likes: int
    coins: int
    favorites: int
    shares: int


class BiliComment(BaseModel):
    """Single Bilibili comment."""

    comment_id: str
    author: str
    text: str
    published_at: datetime
    likes: int


class BiliCommentsPage(BaseModel):
    """Paginated comments response."""

    comments: list[BiliComment]
    has_next: bool


_BASE = "https://api.bilibili.com"


async def video_stats(*, bvid: str, cookies: dict[str, str]) -> BiliVideoStats:
    """Fetch video statistics.

    Raises:
        BilibiliAPIError: API failure or cookies invalid.
    """
    async with httpx.AsyncClient(cookies=cookies) as client:
        resp = await client.get(f"{_BASE}/x/web-interface/view", params={"bvid": bvid})

    if resp.status_code == 429:
        raise BilibiliAPIError("Rate limited (429)")
    if resp.status_code != 200:
        raise BilibiliAPIError(f"API error {resp.status_code}")

    data = resp.json()
    if data.get("code") != 0:
        raise BilibiliAPIError(f"Bilibili error: {data.get('message', 'unknown')}")

    stat = data["data"]["stat"]
    return BiliVideoStats(
        bvid=bvid,
        views=stat["view"],
        likes=stat["like"],
        coins=stat["coin"],
        favorites=stat["favorite"],
        shares=stat["share"],
    )


async def video_comments(
    *, bvid: str, cookies: dict[str, str], max_count: int = 100, page: int = 1
) -> BiliCommentsPage:
    """Fetch video comments (one page).

    Raises:
        BilibiliAPIError: API failure.
    """
    # Need oid (aid) from bvid first
    async with httpx.AsyncClient(cookies=cookies) as client:
        info_resp = await client.get(f"{_BASE}/x/web-interface/view", params={"bvid": bvid})

    if info_resp.status_code != 200:
        raise BilibiliAPIError(f"Failed to resolve bvid: {info_resp.status_code}")

    info_data = info_resp.json()
    if info_data.get("code") != 0:
        raise BilibiliAPIError(f"Bilibili error: {info_data.get('message')}")

    oid = info_data["data"]["aid"]

    async with httpx.AsyncClient(cookies=cookies) as client:
        resp = await client.get(
            f"{_BASE}/x/v2/reply",
            params={"oid": oid, "type": 1, "pn": page, "ps": min(max_count, 20)},
        )

    if resp.status_code != 200:
        raise BilibiliAPIError(f"Comments API error {resp.status_code}")

    data = resp.json()
    if data.get("code") != 0:
        raise BilibiliAPIError(f"Comments error: {data.get('message')}")

    replies = data.get("data", {}).get("replies") or []
    comments = [
        BiliComment(
            comment_id=str(r["rpid"]),
            author=r["member"]["uname"],
            text=r["content"]["message"],
            published_at=datetime.fromtimestamp(r["ctime"], tz=UTC),
            likes=r["like"],
        )
        for r in replies
    ]

    page_info = data.get("data", {}).get("page", {})
    total = page_info.get("count", 0)
    has_next = (page * min(max_count, 20)) < total

    return BiliCommentsPage(comments=comments, has_next=has_next)

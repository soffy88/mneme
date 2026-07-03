"""限流（P2-12）：同一 IP 在窗口内超配额返回 429。"""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as aioredis
from fastapi import HTTPException

from obase.config import settings
from services.ratelimit import check_rate_limit


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_quota():
    scope = f"test-{uuid.uuid4().hex[:8]}"
    ident = "1.2.3.4"
    # 前 3 次放行
    for _ in range(3):
        await check_rate_limit(ident, limit=3, window_seconds=30, scope=scope)
    # 第 4 次超配额 → 429
    with pytest.raises(HTTPException) as ei:
        await check_rate_limit(ident, limit=3, window_seconds=30, scope=scope)
    assert ei.value.status_code == 429

    # 清理键
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.delete(f"ratelimit:{scope}:{ident}")
    await r.aclose()


@pytest.mark.asyncio
async def test_rate_limit_isolated_per_ident():
    scope = f"test-{uuid.uuid4().hex[:8]}"
    # 不同 IP 各自独立计数，互不影响
    await check_rate_limit("10.0.0.1", limit=1, window_seconds=30, scope=scope)
    await check_rate_limit(
        "10.0.0.2", limit=1, window_seconds=30, scope=scope
    )  # 不应因 .1 而被限
    with pytest.raises(HTTPException):
        await check_rate_limit("10.0.0.1", limit=1, window_seconds=30, scope=scope)

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.delete(f"ratelimit:{scope}:10.0.0.1", f"ratelimit:{scope}:10.0.0.2")
    await r.aclose()

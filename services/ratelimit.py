"""轻量 Redis 固定窗口限流（P2-12）。

审计缺口：除 send-code 外无任何限流，匿名 `/v1/solve` 与 LLM 端点可被刷爆算力/额度。
不引入新框架（slowapi 需先改 Master §9），复用已有 redis.asyncio。按 (scope, 客户端 IP)
计数，超过窗口内配额返回 429。
"""

from __future__ import annotations

from typing import Callable

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from obase.config import settings


def _client_ip(request: Request) -> str:
    # 反向代理下优先取 X-Forwarded-For 第一段
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(
    ident: str, *, limit: int, window_seconds: int, scope: str
) -> None:
    """核心限流逻辑（可单测）：同一 (scope, ident) 在 window 内超过 limit 次则抛 429。"""
    key = f"ratelimit:{scope}:{ident}"
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, window_seconds)
        if n > limit:
            ttl = await r.ttl(key)
            raise HTTPException(
                status_code=429, detail=f"请求过于频繁，请 {max(ttl, 1)}s 后重试"
            )
    finally:
        await r.aclose()


def rate_limit(*, limit: int, window_seconds: int, scope: str) -> Callable:
    """构造一个 FastAPI 依赖：按客户端 IP 限流。"""

    async def _dep(request: Request) -> None:
        await check_rate_limit(
            _client_ip(request),
            limit=limit,
            window_seconds=window_seconds,
            scope=scope,
        )

    return _dep

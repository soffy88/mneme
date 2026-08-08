"""健康检查路由（自 main 拆出）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """GET /health — 就绪探针：真的打一次 DB（SELECT 1）。

    DB 不通 → 503。附带 providers 摘要（类型名 + 是否 mock，无密钥）。
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="db unavailable")
    providers: dict = {}
    try:
        from services.providers.setup import provider_status

        providers = provider_status()
    except Exception as e:  # noqa: BLE001 — health 不得因 provider 探测失败变 503
        providers = {"error": type(e).__name__}
    return {
        "status": "ok",
        "version": "0.1.0",
        "service": "mneme-api",
        "providers": providers,
    }


@router.get("/health/providers")
async def health_providers():
    """GET /health/providers — LLM/VLM 是否 mock（pilot / 运维一眼可见）。"""
    from services.providers.setup import provider_status

    return provider_status()

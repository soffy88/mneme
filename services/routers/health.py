"""健康检查路由（自 main 拆出）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.readiness import health_payload, readiness_payload

# Must match `alembic heads` (vocabulary memory nodes).
#
# **加迁移时必须同步改这里**，否则 `/readiness` 会静默掉到 503
# （`migrations = revision == EXPECTED_MIGRATION_HEAD`，而 DB 已经跑到新 head，
# 两边对不上）。这不是我臆想的坑 —— 加 confusable_words 那次迁移后就撞上了，
# alembic 报「upgrade 成功」而 readiness 却红。
EXPECTED_MIGRATION_HEAD = "bkc1a2b3c4d5"

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """GET /health — liveness only; dependency failures belong to /readiness."""
    return health_payload()


@router.get("/readiness")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """GET /readiness — critical DB/migration compatibility probe."""
    database = False
    migrations = False
    try:
        await db.execute(text("SELECT 1"))
        database = True
        revision = (await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).scalar_one_or_none()
        migrations = revision == EXPECTED_MIGRATION_HEAD
    except Exception:
        database = False
    payload, status = readiness_payload(database=database, migrations=migrations)
    if status != 200:
        raise HTTPException(status_code=status, detail=payload)
    return payload


@router.get("/health/providers")
async def health_providers(deep: bool = False):
    """GET /health/providers — LLM/VLM 装配状态 + 网关可达性（运维一眼可见）。

    默认只做**便宜**的端点探活（~3s）。`?deep=1` 会真发一次最小补全并检查返回
    内容（3~30s）—— 这是唯一能识破「HTTP 200 但正文是上游错误串」的检查，
    因为网关把上游故障当正文返回（实测「gpt-5.6-luna 兜底失败」）。
    监控用默认值；怀疑「文本 LLM 调不通」时手工加 `?deep=1`。
    """
    from services.providers.setup import provider_liveness

    return await provider_liveness(deep=deep)


@router.get("/health/metrics")
async def health_metrics():
    """Return privacy-safe process metrics for a liveness/metrics scrape."""

    from services.observability import metrics_snapshot

    return metrics_snapshot()


@router.get("/health/grading")
async def health_grading():
    """Return aggregate deterministic-grading coverage without learner data."""

    from services.grading_observability import grading_snapshot

    return grading_snapshot()

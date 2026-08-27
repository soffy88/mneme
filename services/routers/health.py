"""健康检查路由（自 main 拆出）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.readiness import health_payload, readiness_payload

EXPECTED_MIGRATION_HEAD = "5e7f8a9b0c12"

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
async def health_providers():
    """GET /health/providers — LLM/VLM 是否 mock（pilot / 运维一眼可见）。"""
    from services.providers.setup import provider_status

    return provider_status()


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

"""FSRS 权重优化定时任务（护城河基础设施）。

每周从累积复习日志做一次 torch-free 随机搜索 + 择优，存 cohort='global' 权重。
process_interaction 会自动加载并用于个性化调度。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.fsrs_optimize_service import propose_candidates, select_best_weights

from tasks.celery_app import celery_app

_log = logging.getLogger(__name__)


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            from fsrs import Scheduler
            default = list(Scheduler().parameters)
            candidates = [None, *propose_candidates(default, n=8, jitter=0.08)]
            result = await select_best_weights(db, candidates, cohort="global")
            await db.commit()
            return result
    except Exception as exc:  # 不让任务崩 worker
        _log.exception("fsrs optimize failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.optimize_fsrs_weights")
def optimize_fsrs_weights_task() -> dict:
    return asyncio.run(_run())

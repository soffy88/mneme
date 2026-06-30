"""FSRS 权重优化定时任务（护城河基础设施）。

每周从累积复习日志做一次 torch-free 随机搜索 + 择优，存 cohort='global' 权重。
process_interaction 会自动加载并用于个性化调度。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.fsrs_optimize_service import fit_and_store_weights

from tasks.celery_app import celery_app

_log = logging.getLogger(__name__)


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            # 全体：scipy 导数无关拟合（强于随机搜索）。
            result = await fit_and_store_weights(db, cohort="global")
            # 个体：对复习量足够的活跃学生各自拟合 student:{id}（个体优先加载）。
            from sqlalchemy import func, select
            from services.models import InteractionEvent
            active = (await db.execute(
                select(InteractionEvent.student_id)
                .where(InteractionEvent.student_id.is_not(None))
                .group_by(InteractionEvent.student_id)
                .having(func.count() >= 60)
            )).scalars().all()
            per_student = 0
            for sid in active:
                r = await fit_and_store_weights(db, cohort=f"student:{sid}", student_id=sid)
                if r.get("stored"):
                    per_student += 1
            await db.commit()
            return {**result, "per_student_fitted": per_student}
    except Exception as exc:  # 不让任务崩 worker
        _log.exception("fsrs optimize failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.optimize_fsrs_weights")
def optimize_fsrs_weights_task() -> dict:
    return asyncio.run(_run())

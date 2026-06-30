"""BKT 先验校准定时任务（item 5：数据飞轮）。

每日定时从累积 interaction_events 校准 bkt_priors。与 beat 调度配合（见 celery_app）。
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.calibration_service import calibrate_bkt_priors

from tasks.celery_app import celery_app


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await calibrate_bkt_priors(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.calibrate_bkt_priors")
def calibrate_bkt_priors_task() -> dict:
    """同步入口：跑一次全量 BKT 先验校准。"""
    return asyncio.run(_run())

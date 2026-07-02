"""家长预警定时任务（G.2 定时化）。

每日 20:00 对所有家长-学生绑定跑 5 类预警检查并落库
（此前仅家长手动 POST /v1/parent/alerts/{id}/check 才触发）。
与 beat 调度配合（见 celery_app）。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.alert_service import run_alert_checks
from services.models import ParentStudent

from tasks.celery_app import celery_app


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    pairs_checked = 0
    alerts_written = 0
    try:
        async with factory() as db:
            links = (await db.execute(select(ParentStudent))).scalars().all()
            for link in links:
                written = await run_alert_checks(db, link.student_id, link.parent_id)
                pairs_checked += 1
                alerts_written += len(written)
            await db.commit()
            return {"pairs_checked": pairs_checked, "alerts_written": alerts_written}
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.run_parent_alert_checks")
def run_parent_alert_checks_task() -> dict:
    """同步入口：对全部家长-学生绑定跑一次 5 类预警检查。"""
    return asyncio.run(_run())

"""Agent working-memory TTL 清理定时任务（C5，W2C）。"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from obase.config import settings
from services.memory import cleanup_expired_working_memory

from tasks.celery_app import celery_app


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with factory() as db:
            result = await cleanup_expired_working_memory(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.cleanup_expired_working_memory")
def cleanup_expired_working_memory_task() -> dict:
    """同步入口：物理清除过期的 agent.working_memory 行。"""
    return asyncio.run(_run())

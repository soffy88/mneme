"""合规硬删除定时任务（P1-7）：每日清除软删超宽限期的用户及其全部 PII。"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from obase.config import settings
from services.purge_service import purge_deleted_users

from tasks.celery_app import celery_app


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with factory() as db:
            result = await purge_deleted_users(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.purge_deleted_users")
def purge_deleted_users_task() -> dict:
    """同步入口：物理清除软删超宽限期的用户。"""
    return asyncio.run(_run())

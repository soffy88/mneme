"""护城河实证监控任务：周期性算 KT/FSRS 对真实作答的预测 AUC 并记日志。"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.evaluation_service import evaluate_model

from tasks.celery_app import celery_app

_log = logging.getLogger(__name__)


async def _run() -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            m = await evaluate_model(db)
            _log.info("moat eval: AUC=%s logloss=%s n=%s verdict=%s",
                      m.get("auc"), m.get("logloss"), m.get("n"), m.get("verdict"))
            return m
    except Exception as exc:
        _log.exception("moat eval failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.evaluate_moat")
def evaluate_moat_task() -> dict:
    return asyncio.run(_run())

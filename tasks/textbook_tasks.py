"""教材文件抽取任务（item 7）：上传后触发知识抽取（走可信流水线 + 校验门）。"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.models import TextbookFile
from services.storage import download_file
from services.textbook_extract_service import (
    extract_text_from_pdf_bytes,
    ingest_pipeline_candidates,
)

from tasks.celery_app import celery_app

_log = logging.getLogger(__name__)


async def _run(file_id: str) -> dict:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            tf = (await db.execute(
                select(TextbookFile).where(TextbookFile.id == file_id)
            )).scalar_one_or_none()
            if not tf:
                return {"status": "not_found", "file_id": file_id}
            if not tf.textbook_id:
                # 学生自传暂无 textbook 归属，不灌权威 KU 表（避免污染课程库）
                return {"status": "skipped_no_textbook", "file_id": file_id}

            data = await asyncio.to_thread(download_file, tf.storage_path)
            text = extract_text_from_pdf_bytes(data) if tf.file_type == "pdf" else data.decode("utf-8", "ignore")
            if not text.strip():
                return {"status": "no_text", "file_id": file_id}

            # 可信抽取流水线（structural_chunk→llm_extract_ku→ku_gate_validate）
            from oskill.ku_extract_pipeline import ku_extract_pipeline
            pipeline_result = ku_extract_pipeline(text=text, project_id=str(tf.textbook_id))

            result = await ingest_pipeline_candidates(
                db,
                textbook_id=tf.textbook_id,
                cluster_id=f"{tf.textbook_id}-auto",
                pipeline_result=pipeline_result,
            )
            await db.commit()
            return {"status": "ok", "file_id": file_id, **result}
    except Exception as exc:  # 任务不应 crash worker
        _log.exception("textbook extract failed: %s", exc)
        return {"status": "error", "file_id": file_id, "error": str(exc)}
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.extract_textbook_file")
def extract_textbook_file_task(file_id: str) -> dict:
    return asyncio.run(_run(file_id))

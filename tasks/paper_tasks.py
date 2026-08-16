"""D.2 — Celery task: analyze paper (assembly only, zero business logic).

装配层：读 DB → 从 MinIO 拉图转 base64 → 调 omodul.analyze_paper_workflow → 提交。
真正的 OCR/批改/错题抽取/认知更新全在内核 analyze_paper_workflow 内部完成。
"""
from __future__ import annotations

import asyncio
import base64
import uuid as _uuid

from tasks.celery_app import celery_app


class _RetryableError(Exception):
    """瞬时失败（MinIO 抖动/内核临时异常）→ 走 self.retry 指数重试；
    永久性失败（paper 不存在/无图）直接返回 failed，不重试。"""


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="tasks.paper_tasks.process_paper")
def process_paper(self, paper_id: str) -> dict:
    """Assembly task: read DB → call omodul.analyze_paper_workflow → commit.

    C5 修复：瞬时失败不再裸 return failed（吞错不重试），改用 self.retry(exc=...)
    交给 Celery 按 backoff 重试；重试耗尽后原异常照常上报任务失败。
    """
    try:
        return asyncio.run(_process_paper_async(paper_id))
    except _RetryableError as exc:
        raise self.retry(exc=exc) from exc


async def _process_paper_async(paper_id: str) -> dict:
    from obase.cognitive_store import PgStore
    from obase.config import settings
    from obase.db import SessionLocal
    from obase.oss import get_oss_client
    from omodul.analyze_paper import (
        AnalyzePaperConfig,
        AnalyzePaperInput,
        analyze_paper_workflow,
    )
    from sqlalchemy import select, update

    from services.models import Paper, PaperStatus

    pid = _uuid.UUID(paper_id)

    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one_or_none()
        if not paper:
            return {"status": "failed", "error": "paper not found"}
        if paper.student_id is None:
            return {"status": "failed", "error": "paper has no student"}

        object_names = list((paper.image_urls or {}).values())
        if not object_names:
            await db.execute(update(Paper).where(Paper.id == pid).values(status=PaperStatus.failed))
            await db.commit()
            return {"status": "failed", "error": "no images on paper record"}

        # MinIO object name → base64（内核 OCR 吃 image_b64_list）
        try:
            client = get_oss_client()
            image_b64_list: list[str] = []
            for obj in object_names:
                resp = client.get_object(settings.MINIO_BUCKET, obj)
                try:
                    data = resp.read()
                finally:
                    resp.close()
                    resp.release_conn()
                image_b64_list.append(base64.b64encode(data).decode())
        except Exception as exc:
            # 瞬时失败（MinIO 抖动/网络）→ 重试而非一次性打 failed
            raise _RetryableError(f"image fetch failed: {exc}") from exc

        try:
            store = PgStore(db)
            config = AnalyzePaperConfig(subject=paper.subject or "math")
            inp = AnalyzePaperInput(
                paper_id=pid,
                student_id=paper.student_id,
                image_b64_list=image_b64_list,
            )
            result = await analyze_paper_workflow(config, inp, store, db)
            await db.commit()

            if result.get("status") not in ("completed", "done", None) and result.get("error"):
                # 内核显式失败：落 failed
                await db.execute(update(Paper).where(Paper.id == pid).values(status=PaperStatus.failed))
                await db.commit()
                return {"status": "failed", "error": result.get("error")}

            findings = result.get("findings")
            wrong_count = getattr(findings, "wrong_count", None)
            if wrong_count is None and isinstance(findings, dict):
                wrong_count = findings.get("wrong_count")
            return {"status": "done", "wrong_count": wrong_count}
        except Exception as exc:
            await db.rollback()
            # 内核/LLM/OCR 瞬时异常 → 重试（保留 DB 回滚，避免半成品状态提交）
            raise _RetryableError(str(exc)) from exc

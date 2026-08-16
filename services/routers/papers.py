"""试卷 / 单题快录（自 main 拆出）。"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from obase.db import get_db
from omodul.paper import PaperConfig, PaperUploadInput, upload_paper_workflow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_access,
    get_current_user,
    require_student_access,
)
from services.logging_config import logger
from services.models import Paper, User, WrongQuestion

router = APIRouter(tags=["papers"])

# ===== §3 试卷接口 =====


@router.post("/v1/papers/upload")
async def post_paper_upload(
    student_id: UUID = Query(...),
    file: UploadFile = File(...),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /v1/papers/upload
    上传一张试卷并启动处理流程。鉴权：学生本人或绑定家长。
    """
    config = PaperConfig()

    # 临时保存本地
    temp_dir = "/tmp/mneme_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = Path(temp_dir) / f"{uuid.uuid4()}_{file.filename}"

    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        payload = PaperUploadInput(
            student_id=student_id,
            local_file_path=local_path,
            filename=file.filename or "unknown.jpg",
        )

        result = await upload_paper_workflow(config, payload, db)

        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result["error"])

        # 触发异步分析（OCR→批改→共同断点→认知更新）。
        # 冷启动钩子核心：上传后试卷由 Celery 真正分析，前端轮询 GET /v1/papers/{id} 状态。
        findings = result["findings"]
        try:
            from tasks.paper_tasks import process_paper

            process_paper.delay(findings["paper_id"])
        except Exception as exc:  # noqa: BLE001 — broker 不可用不应阻断上传
            logger.error(
                f"dispatch process_paper failed for {findings.get('paper_id')}: {exc}"
            )

        return findings

    finally:
        # 清理临时文件
        if local_path.exists():
            os.remove(local_path)


@router.get("/v1/papers/{paper_id}")
async def get_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/papers/{id} — 试卷详情 + 错题 + 共同断点。鉴权：卷主本人或绑定家长。"""
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    await _ensure_student_access(db, current_user, paper.student_id)
    wqs = (
        (
            await db.execute(
                select(WrongQuestion).where(WrongQuestion.paper_id == paper_id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "paper": {
            "id": str(paper.id),
            "student_id": str(paper.student_id),
            "status": paper.status.value if paper.status else None,
            "subject": paper.subject,
            "created_at": paper.created_at.isoformat() if paper.created_at else None,
        },
        "wrong_questions": [
            {
                "id": str(w.id),
                "ku_ids": list((w.knowledge_points or {}).keys()),
                "error_type": w.error_type.value if w.error_type else None,
            }
            for w in wqs
        ],
    }


@router.get("/v1/papers")
async def list_papers(
    student_id: UUID = Query(...),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/papers — 试卷列表。鉴权：学生本人或绑定家长。"""
    stmt = (
        select(Paper)
        .where(Paper.student_id == student_id)
        .order_by(Paper.created_at.desc())
    )
    papers = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(p.id),
            "status": p.status.value if p.status else None,
            "subject": p.subject,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in papers
    ]



# ===== §D.4 单题快录 =====


@router.post("/v1/papers/quick")
async def post_quick_question(
    student_id: UUID = Query(...),
    kc_hint: str | None = Query(None),
    file: UploadFile = File(...),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/papers/quick — 单题快录，立即创建 WrongQuestion。鉴权：学生本人或绑定家长。"""
    import uuid as _uuid

    wq_id = _uuid.uuid4()
    wq = WrongQuestion(
        id=wq_id,
        student_id=student_id,
        subject="math",
        knowledge_points={kc_hint: 1.0} if kc_hint else {},
    )
    db.add(wq)
    await db.commit()
    return {"question_id": str(wq_id), "status": "pending_ocr", "kc_hint": kc_hint}



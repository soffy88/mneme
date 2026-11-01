"""组卷打印路由（学生本人，需登录；命名避开来源试卷 papers）。

- POST /v1/exam-sheets              创建组卷（仅本人；规格过拼装门禁）
- GET  /v1/exam-sheets              列表（仅本人，叠加实时作答统计）
- GET  /v1/exam-sheets/{sheet_id}   详情（仅本人，他人 404）
- GET  /v1/exam-sheets/{sheet_id}/export?format=html|docx  导出（仅本人）
- POST /v1/exam-sheets/{sheet_id}/results  回填结果（仅本人；重复 409）

回填口径（写死）：同一题在同一组卷内重复提交返回 409；回填只追加
QuestionRecord + FSRS 排期，不写 BKT 掌握度（见 exam_sheet.py）。
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from urllib.parse import quote

from services.exam_sheet import (
    SheetResultsError,
    apply_sheet_results,
    assemble_exam_sheet,
    render_sheet_docx,
    render_sheet_html,
    sheet_attempt_stats,
    sheet_file_name,
    validate_exam_sheet_spec,
)
from services.models import ExamSheet, User, WrongQuestion

router = APIRouter(prefix="/v1/exam-sheets", tags=["exam-sheets"])


class ExamSheetCreate(BaseModel):
    spec: dict


class SheetResultsCreate(BaseModel):
    results: list[dict]


def _present(
    row: ExamSheet, stats: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    spec = copy.deepcopy(row.spec)
    for question in spec.get("questions", []):
        stat = stats.get(str(question["wrong_question_id"]), {})
        question["attempts"] = int(stat.get("attempts", 0))
        question["last_is_correct"] = stat.get("last_is_correct")
        question["last_answered_at"] = stat.get("last_answered_at")
    return {
        "id": row.id,
        "student_id": str(row.student_id),
        "spec": spec,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_owned_sheet(
    db: AsyncSession, sheet_id: str, student_id: uuid.UUID
) -> ExamSheet:
    row = await db.get(ExamSheet, sheet_id)
    if row is None or row.student_id != student_id:
        raise HTTPException(status_code=404, detail="组卷不存在")
    return row


async def _owned_rows(
    db: AsyncSession, student_id: uuid.UUID, wq_ids: list[str]
) -> list[WrongQuestion]:
    parsed_ids: list[uuid.UUID] = []
    for wq_id in wq_ids:
        try:
            parsed_ids.append(uuid.UUID(wq_id))
        except ValueError:
            # 非法 UUID 形态：查无此题，拼装门禁报 question_not_owned。
            continue
    if not parsed_ids:
        return []
    rows = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id.in_(parsed_ids),
                WrongQuestion.student_id == student_id,
            )
        )
    ).scalars().all()
    return list(rows)


@router.post("")
async def create_exam_sheet(
    payload: ExamSheetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    spec = dict(payload.spec)
    spec["student_id"] = str(current_user.id)
    spec_id = spec.get("id")
    if isinstance(spec_id, str) and spec_id.strip():
        if await db.get(ExamSheet, spec_id) is not None:
            raise HTTPException(status_code=409, detail=f"组卷 id {spec_id!r} 已存在")
    issues = validate_exam_sheet_spec(spec)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "组卷规格未通过校验",
                "issues": [vars(i) for i in issues],
            },
        )
    wq_ids = [str(item["wrong_question_id"]) for item in spec["items"]]
    rows = await _owned_rows(db, current_user.id, wq_ids)
    owned = [
        {
            "id": str(r.id),
            "subject": r.subject,
            "question_text": r.question_text,
            "correct_answer": r.correct_answer,
        }
        for r in rows
    ]
    stats = await sheet_attempt_stats(db, current_user.id, wq_ids)
    assembled, assemble_issues = assemble_exam_sheet(spec, owned, stats)
    if assembled is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "组卷拼装失败",
                "issues": [vars(i) for i in assemble_issues],
            },
        )
    row = ExamSheet(id=spec_id, student_id=current_user.id, spec=assembled)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _present(row, stats)


@router.get("")
async def list_exam_sheets(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(ExamSheet)
            .where(ExamSheet.student_id == current_user.id)
            .order_by(ExamSheet.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    all_ids: list[str] = []
    for row in rows:
        all_ids.extend(
            str(q["wrong_question_id"]) for q in row.spec.get("questions", [])
        )
    stats = await sheet_attempt_stats(db, current_user.id, all_ids)
    return {"items": [_present(r, stats) for r in rows], "total": len(rows)}


@router.get("/{sheet_id}")
async def get_exam_sheet(
    sheet_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_owned_sheet(db, sheet_id, current_user.id)
    ids = [str(q["wrong_question_id"]) for q in row.spec.get("questions", [])]
    stats = await sheet_attempt_stats(db, current_user.id, ids)
    return _present(row, stats)


@router.get("/{sheet_id}/export")
async def export_exam_sheet(
    sheet_id: str,
    format: str = Query(default="html", pattern="^(html|docx)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await _get_owned_sheet(db, sheet_id, current_user.id)
    title = str(row.spec.get("title") or "exam-sheet")
    if format == "docx":
        content = render_sheet_docx(row.spec)
        media_type = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
        filename = sheet_file_name(title, "docx")
    else:
        content = render_sheet_html(row.spec).encode("utf-8")
        media_type = "text/html; charset=utf-8"
        filename = sheet_file_name(title, "html")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            # 文件名含中文时裸写进 header 会触发 latin-1 编码失败：
            # ASCII fallback + RFC 5987 filename* 双写。
            "Content-Disposition": (
                f'attachment; filename="exam-sheet.{format}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/{sheet_id}/results")
async def record_exam_sheet_results(
    sheet_id: str,
    payload: SheetResultsCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_owned_sheet(db, sheet_id, current_user.id)
    try:
        recorded = await apply_sheet_results(
            db, row, current_user.id, payload.results, datetime.now(timezone.utc)
        )
    except SheetResultsError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=exc.status,
            detail={
                "message": "组卷结果回填失败",
                "issues": [vars(i) for i in exc.issues],
            },
        )
    # commit 后再碰 row.id 会触发过期刷新（MissingGreenlet）：先快照。
    sheet_id = row.id
    await db.commit()
    return {"sheet_id": sheet_id, "recorded": recorded}

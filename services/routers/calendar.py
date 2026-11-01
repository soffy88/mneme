"""日历视图路由（DeepTutor 任务板＋日历方法，干净重写）。

只读合并视图：本人的任务到期日＋本人错题的 FSRS 到期日，按日聚合。
窗口默认当天起 14 天；start/end 均为 ISO 日期，start > end 判 422。
"""

from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.auth_deps import get_current_user
from services.i18n import negotiate_language, t
from services.models import StudyTask, User, WrongQuestion
from services.task_board import build_calendar

router = APIRouter(prefix="/v1/calendar", tags=["calendar"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


@router.get("")
async def get_calendar(
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    today = date.today()
    try:
        start_date = date.fromisoformat(start) if start else today
        end_date = date.fromisoformat(end) if end else start_date + timedelta(days=13)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=t("task.invalid_payload", lg)
        )
    if start_date > end_date:
        raise HTTPException(
            status_code=422, detail=t("task.invalid_payload", lg)
        )
    task_rows = (
        await db.execute(
            select(StudyTask)
            .where(StudyTask.student_id == current_user.id)
            .where(StudyTask.archived.is_(False))
            .where(StudyTask.due_date.is_not(None))
            .where(StudyTask.due_date >= start_date)
            .where(StudyTask.due_date <= end_date)
        )
    ).scalars().all()
    tasks: list[dict[str, Any]] = [
        {
            "id": str(row.id),
            "title": row.title,
            "status": row.status,
            "archived": bool(row.archived),
            "due_date": row.due_date.isoformat() if row.due_date else None,
        }
        for row in task_rows
    ]
    wq_rows = (
        await db.execute(
            select(WrongQuestion).where(WrongQuestion.student_id == current_user.id)
        )
    ).scalars().all()
    reviews: list[dict[str, Any]] = []
    for wq in wq_rows:
        due = wq.fsrs_due
        if due is None:
            continue
        due_day = due.astimezone(timezone.utc).date() if due.tzinfo else due.date()
        if not start_date <= due_day <= end_date:
            continue
        reviews.append(
            {
                "wrong_question_id": str(wq.id),
                "subject": wq.subject,
                "fsrs_due": due_day.isoformat(),
            }
        )
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days": build_calendar(tasks, reviews, start_date, end_date),
    }

"""任务板路由（DeepTutor 任务板＋日历方法，干净重写）。

仅本人可见：他人 id 一律 404，不泄露存在性。创建/更新先经
services/task_board.py 的 validate_task_payload 校验（调用方先合并）；
移动只改 status/position（apply_move）。用户可见字符串走 t()。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.auth_deps import get_current_user
from services.i18n import negotiate_language, t
from services.models import StudyTask, User
from services.task_board import (
    TaskIssue,
    apply_move,
    sort_tasks,
    validate_task_payload,
)

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: StudyTask) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "student_id": str(row.student_id),
        "title": row.title,
        "notes": row.notes,
        "status": row.status,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "position": row.position,
        "archived": bool(row.archived),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _row_dict(row: StudyTask) -> dict[str, Any]:
    view = _view(row)
    return view


def _issues_or_422(issues: list[TaskIssue], lg: str) -> None:
    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("task.invalid_payload", lg),
                "issues": [issue.to_dict() for issue in issues],
            },
        )


async def _own_row(
    db: AsyncSession, task_id: str, current_user: User, lg: str
) -> StudyTask:
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail=t("task.not_found", lg))
    row = await db.get(StudyTask, task_uuid)
    if row is None or row.student_id != current_user.id:
        raise HTTPException(status_code=404, detail=t("task.not_found", lg))
    return row


@router.post("")
async def create_task(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    data = {
        "title": payload.get("title"),
        "notes": payload.get("notes"),
        "status": payload.get("status", "todo"),
        "due_date": payload.get("due_date"),
        "position": payload.get("position", 0),
    }
    _issues_or_422(validate_task_payload(data), lg)
    task_uuid: Optional[uuid.UUID] = None
    raw_id = payload.get("id")
    if raw_id is not None:
        try:
            task_uuid = uuid.UUID(str(raw_id))
        except (ValueError, TypeError):
            _issues_or_422(
                [TaskIssue("id", "bad_id", "id must be a UUID string")], lg
            )
        if await db.get(StudyTask, task_uuid) is not None:
            raise HTTPException(
                status_code=409, detail=t("task.duplicate_id", lg)
            )
    due = None
    if data["due_date"] is not None:
        due = datetime.strptime(data["due_date"], "%Y-%m-%d").date()
    row = StudyTask(
        student_id=current_user.id,
        title=data["title"],
        notes=data["notes"],
        status=data["status"],
        due_date=due,
        position=data["position"],
        archived=False,
    )
    if task_uuid is not None:
        row.id = task_uuid
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("")
async def list_tasks(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(StudyTask).where(StudyTask.student_id == current_user.id)
    if not include_archived:
        stmt = stmt.where(StudyTask.archived.is_(False))
    rows = (await db.execute(stmt)).scalars().all()
    ordered = sort_tasks([_row_dict(row) for row in rows])
    return {"items": ordered}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _own_row(db, task_id, current_user, lg)
    return _view(row)


@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _own_row(db, task_id, current_user, lg)
    merged = {
        "title": payload.get("title", row.title),
        "notes": payload.get("notes", row.notes),
        "status": payload.get("status", row.status),
        "due_date": payload.get(
            "due_date", row.due_date.isoformat() if row.due_date else None
        ),
        "position": payload.get("position", row.position),
    }
    _issues_or_422(validate_task_payload(merged), lg)
    row.title = merged["title"]
    row.notes = merged["notes"]
    row.status = merged["status"]
    row.due_date = (
        datetime.strptime(merged["due_date"], "%Y-%m-%d").date()
        if merged["due_date"] is not None
        else None
    )
    row.position = merged["position"]
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.post("/{task_id}/move")
async def move_task(
    task_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _own_row(db, task_id, current_user, lg)
    updated, issues = apply_move(
        _row_dict(row),
        status=payload.get("status"),
        position=payload.get("position"),
    )
    _issues_or_422(issues, lg)
    row.status = updated["status"]
    row.position = updated["position"]
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.post("/{task_id}/archive")
async def archive_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _own_row(db, task_id, current_user, lg)
    row.archived = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.post("/{task_id}/restore")
async def restore_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _own_row(db, task_id, current_user, lg)
    row.archived = False
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view

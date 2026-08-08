"""康奈尔笔记云端进度路由（自 main 拆出）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.auth_deps import (
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.cornell_merge import CornellMergeError
from services.cornell_service import (
    delete_progress as cornell_delete_progress,
)
from services.cornell_service import (
    get_progress as cornell_get_progress,
)
from services.cornell_service import (
    list_progress as cornell_list_progress,
)
from services.cornell_service import (
    put_progress as cornell_put_progress,
)
from services.models import User

router = APIRouter(tags=["cornell"])


class CornellProgressPut(BaseModel):
    """客户端上传的进度 State（mastered/collapsed/selfTest/…）。"""

    state: dict


@router.get("/v1/cornell/{student_id}/progress")
async def list_cornell_progress(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """列出该学生全部康奈尔课题云端进度摘要。"""
    items = await cornell_list_progress(db, student_id)
    return {"items": items}


@router.get("/v1/cornell/{student_id}/progress/{topic_id}")
async def get_cornell_progress(
    student_id: UUID,
    topic_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """拉取单课题进度；无记录时 404。"""
    row = await cornell_get_progress(db, student_id, topic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no cloud progress for topic")
    return row


@router.put("/v1/cornell/{student_id}/progress/{topic_id}")
async def put_cornell_progress(
    student_id: UUID,
    topic_id: str,
    body: CornellProgressPut,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """合并写入云端进度（并集）。仅学生本人。不写 kc_mastery。"""
    _ensure_student_self(current_user, student_id)
    try:
        result = await cornell_put_progress(db, student_id, topic_id, body.state)
    except CornellMergeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await db.commit()
    return result


@router.delete("/v1/cornell/{student_id}/progress/{topic_id}")
async def delete_cornell_progress(
    student_id: UUID,
    topic_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除云端进度（本地 localStorage 不动）。仅学生本人。"""
    _ensure_student_self(current_user, student_id)
    existed = await cornell_delete_progress(db, student_id, topic_id)
    await db.commit()
    return {"deleted": existed, "topic_id": topic_id}

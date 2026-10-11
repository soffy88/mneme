"""Immersive Reading 路由（/v1/reading/*）。

- ``GET  /v1/reading/sources``                       书单 + 可读原文的教材 + 本人阅读位置
- ``GET  /v1/reading/textbooks/{textbook_id}``       教材原文阅读块（分页 offset/limit）
- ``GET  /v1/reading/position/{student_id}``         本人某来源的阅读位置
- ``PUT  /v1/reading/position``                      保存本人阅读位置（upsert）

位置读写仅学生本人（``_ensure_student_self``，家长也 403）。阅读位置只是进度，
不写任何学习证据、不碰门控。"检查一下"答题仍走既有 /mcp/RequestQuestion →
/mcp/SubmitAnswer，"解释这句"仍走既有 /v1/chat/turn——本路由不新增判分路径。
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services import reading_service
from services.auth_deps import _ensure_student_self, get_current_user
from services.models import User
from services.reading_service import ReadingError

router = APIRouter(prefix="/v1/reading", tags=["reading"])


class SavePositionReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID
    source_kind: Literal["book", "textbook"]
    source_id: str = Field(min_length=1, max_length=64)
    block_index: int = Field(ge=0, le=100_000)
    block_id: Optional[str] = Field(default=None, max_length=64)
    total_blocks: Optional[int] = Field(default=None, ge=0, le=100_000)


@router.get("/sources")
async def reading_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await reading_service.list_sources(db, current_user.id)


@router.get("/textbooks/{textbook_id}")
async def reading_textbook(
    textbook_id: str,
    offset: int = Query(0, ge=0, le=100_000),
    limit: int = Query(40, ge=1, le=reading_service.MAX_PAGE),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        out = await reading_service.textbook_blocks(
            db, textbook_id, offset=offset, limit=limit
        )
    except ReadingError as exc:
        raise HTTPException(422, str(exc)) from exc
    if out is None:
        raise HTTPException(404, "这本教材暂时没有可读的原文")
    return out


@router.get("/position/{student_id}")
async def reading_position(
    student_id: uuid.UUID,
    source_kind: Literal["book", "textbook"] = Query(...),
    source_id: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _ensure_student_self(current_user, student_id)
    try:
        pos = await reading_service.get_position(db, student_id, source_kind, source_id)
    except ReadingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"position": pos}


@router.put("/position")
async def save_reading_position(
    req: SavePositionReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _ensure_student_self(current_user, req.student_id)
    try:
        pos = await reading_service.save_position(
            db,
            req.student_id,
            req.source_kind,
            req.source_id,
            block_index=req.block_index,
            block_id=req.block_id,
            total_blocks=req.total_blocks,
        )
    except ReadingError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return {"position": pos}

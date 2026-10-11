"""学习者笔记本路由（DeepTutor Notebook 对标）。

- GET    /v1/notebooks                               我的笔记本列表（含条数）
- POST   /v1/notebooks                               新建
- GET    /v1/notebooks/{notebook_id}                 详情 + 记录
- PATCH  /v1/notebooks/{notebook_id}                 改名/改描述
- DELETE /v1/notebooks/{notebook_id}                 删除（连同记录）
- POST   /v1/notebooks/save                          「存到笔记本」一键入口（按 id 或名字，没有就建）
- POST   /v1/notebooks/{notebook_id}/records         新增记录
- PATCH  /v1/notebooks/{notebook_id}/records/{rid}   修改记录
- DELETE /v1/notebooks/{notebook_id}/records/{rid}   删除记录

权限：owner-only（学生本人）。现有授权模型（agent.user_grants）没有"家长读孩子笔记"
授权，家长账号一律 403；别人的笔记本 403、不存在 404。业务逻辑在
services/notebook_service.py；笔记永不进门控。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import User, UserRole

router = APIRouter(tags=["notebooks"])

SourceType = Literal["chat", "book_block", "solve", "visualize", "research", "cowriter", "free_text"]


class NotebookCreateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)


class NotebookUpdateReq(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)


class RecordCreateReq(BaseModel):
    source_type: SourceType
    content: str = Field(..., min_length=1, max_length=20000)
    source_id: Optional[str] = Field(None, max_length=100)
    kc_id: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(None, max_length=200)
    metadata: Optional[dict[str, Any]] = None


class RecordUpdateReq(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=20000)


class SaveReq(RecordCreateReq):
    notebook_id: Optional[str] = Field(None, max_length=50)
    notebook_name: Optional[str] = Field(None, max_length=100)


def _require_learner(user: User) -> User:
    """笔记本是学习者自己的：只有学生账号能用（家长只读口径下也无授权可读）。"""
    if user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="笔记本只对学生本人开放")
    return user


async def learner(current_user: User = Depends(get_current_user)) -> User:
    return _require_learner(current_user)


def _http(exc: Exception) -> HTTPException:
    from services.notebook_service import NotebookError

    assert isinstance(exc, NotebookError)
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/v1/notebooks")
async def list_notebooks(db: AsyncSession = Depends(get_db), user: User = Depends(learner)):
    from services import notebook_service as svc

    return {"notebooks": await svc.list_notebooks(db, user.id), "source_types": list(svc.SOURCE_TYPES)}


@router.post("/v1/notebooks", status_code=201)
async def create_notebook(
    req: NotebookCreateReq, db: AsyncSession = Depends(get_db), user: User = Depends(learner)
):
    from services import notebook_service as svc

    try:
        nb = await svc.create_notebook(db, user.id, name=req.name, description=req.description)
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return nb


@router.post("/v1/notebooks/save", status_code=201)
async def save_to_notebook(req: SaveReq, db: AsyncSession = Depends(get_db), user: User = Depends(learner)):
    from services import notebook_service as svc

    try:
        out = await svc.save_to_notebook(
            db,
            user.id,
            notebook_id=req.notebook_id,
            notebook_name=req.notebook_name,
            source_type=req.source_type,
            content=req.content,
            source_id=req.source_id,
            kc_id=req.kc_id,
            title=req.title,
            metadata=req.metadata,
        )
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return out


@router.get("/v1/notebooks/{notebook_id}")
async def get_notebook(
    notebook_id: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(learner),
):
    from services import notebook_service as svc

    try:
        return await svc.get_notebook(db, user.id, notebook_id, limit=limit, offset=offset)
    except svc.NotebookError as exc:
        raise _http(exc) from None


@router.patch("/v1/notebooks/{notebook_id}")
async def update_notebook(
    notebook_id: str,
    req: NotebookUpdateReq,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(learner),
):
    from services import notebook_service as svc

    try:
        nb = await svc.update_notebook(db, user.id, notebook_id, name=req.name, description=req.description)
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return nb


@router.delete("/v1/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(learner)):
    from services import notebook_service as svc

    try:
        await svc.delete_notebook(db, user.id, notebook_id)
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return {"deleted": notebook_id}


@router.post("/v1/notebooks/{notebook_id}/records", status_code=201)
async def add_record(
    notebook_id: str,
    req: RecordCreateReq,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(learner),
):
    from services import notebook_service as svc

    try:
        rec = await svc.add_record(
            db,
            user.id,
            notebook_id,
            source_type=req.source_type,
            content=req.content,
            source_id=req.source_id,
            kc_id=req.kc_id,
            title=req.title,
            metadata=req.metadata,
        )
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return rec


@router.patch("/v1/notebooks/{notebook_id}/records/{record_id}")
async def update_record(
    notebook_id: str,
    record_id: str,
    req: RecordUpdateReq,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(learner),
):
    from services import notebook_service as svc

    try:
        rec = await svc.update_record(db, user.id, notebook_id, record_id, title=req.title, content=req.content)
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return rec


@router.delete("/v1/notebooks/{notebook_id}/records/{record_id}")
async def delete_record(
    notebook_id: str,
    record_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(learner),
):
    from services import notebook_service as svc

    try:
        await svc.delete_record(db, user.id, notebook_id, record_id)
    except svc.NotebookError as exc:
        raise _http(exc) from None
    await db.commit()
    return {"deleted": record_id}

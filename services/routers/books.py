"""活书编译入口路由（W3 Book Engine 的生产入口）。

- POST /v1/books/compile             发起编译（学生本人 / admin），返回 book_id + status
- GET  /v1/books/{book_id}/status     轮询编译状态
- GET  /v1/books/compile/textbooks    可编译的教材（有知识簇的）

注意 GET /v1/books 是另一张表（course_books，NCE 课本），与本文件无关；活书的
只读阅读器仍是 /mcp/ListBooks + /mcp/GetBook。业务逻辑全在
services/book_compile_service.py，路由只做鉴权与 HTTP 映射。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import User, UserRole

_log = logging.getLogger(__name__)

router = APIRouter(tags=["books"])


class CompileBookReq(BaseModel):
    textbook_id: str = Field(..., min_length=1, max_length=50)


def _is_admin(user: User) -> bool:
    from obase.admin_identity import is_admin

    return is_admin(user)


@router.get("/v1/books/compile/textbooks")
async def compilable_textbooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.book_compile_service import list_compilable_textbooks, per_user_daily_limit

    return {
        "textbooks": await list_compilable_textbooks(db),
        "daily_limit": per_user_daily_limit(),
        "is_admin": _is_admin(current_user),
    }


@router.post("/v1/books/compile", status_code=202)
async def compile_book(
    req: CompileBookReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发起一本活书的编译（约 $0.5/本）。

    权限：admin（ADMIN_USER_IDS）或学生本人（书记在发起人名下计限额）；家长账号不能
    发起——家长只读，不替孩子消耗额度（同 _ensure_student_self 的写操作口径）。
    """
    from services import book_compile_service as svc

    admin = _is_admin(current_user)
    if not admin and current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="仅学生本人或管理员可以生成活书")

    try:
        job = await svc.create_compile_job(
            db,
            requested_by=str(current_user.id),
            textbook_id=req.textbook_id,
            is_admin=admin,
        )
    except svc.CompileRejected as rej:
        raise HTTPException(status_code=rej.status_code, detail=rej.detail) from None

    if not job["deduplicated"]:
        try:
            svc.enqueue_compile(job["book_id"])
        except Exception as exc:  # noqa: BLE001 - broker 不可用
            _log.exception("enqueue book compile failed")
            await svc.mark_error(db, job["book_id"], f"任务投递失败：{type(exc).__name__}")
            raise HTTPException(status_code=503, detail="编译队列暂不可用，请稍后再试") from None
    return job


@router.get("/v1/books/{book_id}/status")
async def compile_status(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.book_compile_service import get_compile_status

    st = await get_compile_status(db, book_id)
    if st is None:
        raise HTTPException(status_code=404, detail="book not found")
    # 书是共享内容，状态谁都能看；但发起人身份只回给本人/admin。
    requester = st.pop("requested_by")
    st["requested_by_me"] = requester is not None and requester == str(current_user.id)
    if _is_admin(current_user):
        st["requested_by"] = requester
    return st

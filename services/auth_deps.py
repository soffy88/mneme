"""auth_deps — 服务层共享的认证/越权依赖（单源）。

`get_current_user` / `require_student_access` / `_ensure_student_access` /
`_ensure_student_self` 原在 `services/main.py`；W2b 起 `services/mcp_router.py`
（studio 浏览器直连的 /mcp 工具面）也需同一套越权规则，故抽到此处，两个 router
均从这里 import，避免同一逻辑两份实现（CLAUDE.md 单源红线）与 main↔mcp_router 循环导入。

只依赖 obase.auth（token 原语）+ obase.db + services.models，绝不 import main/mcp_router。
"""

from __future__ import annotations

import uuid
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.auth import decode_access_token
from obase.db import get_db
from services.models import ParentStudent, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/auth/login", auto_error=False)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    stmt = select(User).where(User.id == uuid.UUID(user_id), User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_student_access(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """越权防护：仅学生本人或其绑定家长可访问该学生数据（合规红线，含未成年人）。
    student_id 从路径自动解析。"""
    if current_user.id == student_id:
        return current_user
    link = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="无权访问该学生数据")
    return current_user


async def _ensure_student_access(
    db: AsyncSession, current_user: User, student_id: Optional[UUID]
) -> None:
    """IDOR 防护（student_id 在 body/query/关联行里的场景）：
    仅学生本人或其绑定家长，否则 403。与 require_student_access 同规则。"""
    if student_id is None or current_user.id == student_id:
        return
    link = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="无权访问该学生数据")


def _ensure_student_self(current_user: User, student_id: Optional[UUID]) -> None:
    """学习数据写操作（答题/会话/任务完成）仅学生本人可执行；
    家长只读，不可替孩子写认知数据（否则污染 BKT/FSRS 档案）。"""
    if student_id is not None and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="仅学生本人可执行该操作")

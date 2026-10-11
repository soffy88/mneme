"""Co-Writer 路由（DeepTutor Co-Writer 对标，写作教练，不代写）。

- POST /v1/cowriter/suggest   对学习者自己的文字给修改建议（diff hunks，逐块接受/拒绝）
- GET  /v1/cowriter/limits    今日已用 / 每日上限 / 各动作的长度倍率

权限：学生本人（家长 403——家长不替孩子写，也不替孩子消耗额度）。草稿存笔记本走
POST /v1/notebooks/save（source_type=cowriter）。业务规则全在
services/cowriter_service.py。
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import User, UserRole

router = APIRouter(tags=["cowriter"])


class SuggestReq(BaseModel):
    action: Literal["rewrite", "expand", "shorten", "grammar", "outline"]
    text: str = Field(..., min_length=1, max_length=4000)
    instruction: Optional[str] = Field(None, max_length=200)
    cite: bool = False


def _is_admin(user: User) -> bool:
    from obase.admin_identity import is_admin

    return bool(is_admin(user))


async def learner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="写作助手只对学生本人开放")
    return current_user


@router.get("/v1/cowriter/limits")
async def cowriter_limits(db: AsyncSession = Depends(get_db), user: User = Depends(learner)):
    from services import cowriter_service as svc

    return {
        "used_today": await svc.used_today(db, user.id),
        "daily_limit": svc.daily_limit(),
        "is_admin": _is_admin(user),
        "actions": list(svc.ACTIONS),
        "length_ratio": svc.LENGTH_RATIO,
        "min_input_units": svc.MIN_INPUT_UNITS,
    }


@router.post("/v1/cowriter/suggest")
async def cowriter_suggest(req: SuggestReq, db: AsyncSession = Depends(get_db), user: User = Depends(learner)):
    from services import cowriter_service as svc

    try:
        out = await svc.suggest(
            db,
            student_id=user.id,
            action=req.action,
            user_text=req.text,
            instruction=req.instruction,
            cite=req.cite,
            is_admin=_is_admin(user),
        )
    except svc.CowriterError as exc:
        # 账本行（refused/failed）也要落库，限额才算得准
        await db.commit()
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}
        ) from None
    await db.commit()
    return out

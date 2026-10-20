"""AetherViz 知识点互动课 REST（服务层）：生成/取缓存 + 课内小测验经 SubmitAnswer 回写。

- ``POST /v1/viz/ku``：``{ku_id, weak_points?, force?, wait_seconds?}`` → ready(html) / pending(轮询) / failed。
  与 MCP ``GenerateKUVisualization`` 同一实现、同一授权（services.tool_grants，学生默认放行）。
- ``POST /v1/viz/quiz-answer``：宿主页收到 iframe ``postMessage({source:'mneme-viz',type:'quiz-answer'})``
  后转交；答案键在服务端，只经 gate pending → ``tool_submit_answer`` 写 BKT。
HTML 只应放进 ``sandbox="allow-scripts"`` 的 iframe（无 allow-same-origin）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.auth_deps import get_current_user
from services.models import User

router = APIRouter(prefix="/v1/viz", tags=["viz"])

TOOL = "GenerateKUVisualization"


class VizReq(BaseModel):
    ku_id: str = Field(..., max_length=64)
    weak_points: Optional[list[str]] = Field(default=None, max_length=8)
    force: bool = False
    wait_seconds: float = Field(default=25.0, ge=0, le=60)


class VizQuizAnswerReq(BaseModel):
    ku_id: str = Field(..., max_length=64)
    variant: str = Field(..., max_length=16)
    quiz_id: str = Field(..., max_length=16)
    choice: int = Field(..., ge=0, le=5)


async def generate_ku_visualization(db: AsyncSession, current_user: User, req: VizReq) -> dict:
    from services import viz_generator as vg
    from services.tool_grants import is_tool_allowed

    if not await is_tool_allowed(db, current_user, TOOL):
        raise HTTPException(status_code=403, detail=f"未获授权使用 {TOOL}")
    if req.force:
        from obase.admin_identity import is_admin

        if not is_admin(current_user):
            raise HTTPException(status_code=403, detail="force 仅管理员可用")
    weak = [str(w)[:80] for w in (req.weak_points or [])]
    try:
        return await vg.get_or_generate(req.ku_id, weak, force=req.force, wait_seconds=req.wait_seconds)
    except vg.VizError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/ku")
async def post_viz_ku(
    req: VizReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await generate_ku_visualization(db, current_user, req)


@router.post("/quiz-answer")
async def post_viz_quiz_answer(
    req: VizQuizAnswerReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from services import viz_generator as vg
    from services.tool_grants import is_tool_allowed

    if not await is_tool_allowed(db, current_user, TOOL):
        raise HTTPException(status_code=403, detail=f"未获授权使用 {TOOL}")
    return await vg.submit_viz_quiz_answer(
        db, current_user, ku_id=req.ku_id, variant=req.variant, quiz_id=req.quiz_id, choice=req.choice
    )

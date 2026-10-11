"""Animator 路由：``POST /v1/animate {kind, params}`` → 确定性步骤动画时间线（纯数据）。

时间线由 ``services.animate_service`` 从确定性内核编排而来，客户端在 sandbox iframe
（只给 allow-scripts）里用自托管播放器 ``/v1/edu-assets/mneme-animator-1/player.js``
渲染。服务端不执行任何 LLM 生成的代码。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from services.animate_service import AnimateError, AnimateRequest, build_timeline
from services.auth_deps import get_current_user
from services.models import User

router = APIRouter(prefix="/v1/animate", tags=["animate"])


@router.post("")
async def animate(
    req: AnimateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await build_timeline(req.kind, req.params)
    except AnimateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

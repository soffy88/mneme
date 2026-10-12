"""英语作答确定性批改路由。

- ``POST /v1/english/check`` → 答案等价（fill / order / dictation，缩写感知）、规范化读法、
  he/she 指代错误与改法、目标句型是否用上、听写编辑数（JSON）。不调用 LLM。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from oskill.english_answer_check_skill import EnglishCheckRequest

from services.auth_deps import get_current_user
from services.english_check_service import check
from services.models import User

router = APIRouter(prefix="/v1/english", tags=["english"])


@router.post("/check")
async def check_english(
    request: EnglishCheckRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return check(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

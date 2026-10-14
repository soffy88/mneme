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
        result = check(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from services.question_record_service import record_question

    await record_question(
        student_id=getattr(current_user, "id", None),
        source="solver",
        subject="english",
        question_text=request.context or None,
        student_answer=request.text,
        correct_answer=(request.accepted[0] if request.accepted else None),
        is_correct=result.get("answer_ok") if result.get("answer_checked") else None,
        grader="kernel",
        auto_wrong_book=bool(request.context),
        meta={"tool": "english.check", "type": request.type},
    )
    return result

"""立体几何交互解题路由。

- ``POST /v1/geometry/solid/solve``  → 精确答案 + 分步解析 + 3D 模型数据（JSON）
- ``POST /v1/geometry/solid/lesson`` → 自包含交互课页面（HTML）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from oprim.solid_geometry import SolidGeometrySpec

from services.auth_deps import get_current_user
from services.models import User
from services.solid_geometry_service import (
    SolidGeometryError,
    render_lesson_html,
    solve,
)

router = APIRouter(prefix="/v1/geometry/solid", tags=["geometry"])


@router.post("/solve")
async def solve_solid_geometry(
    spec: SolidGeometrySpec,
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        solution = await solve(spec)
    except SolidGeometryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from services.question_record_service import record_question

    await record_question(
        student_id=getattr(current_user, "id", None),
        source="solver",
        subject="math",
        question_text=str(solution.get("title") or "立体几何"),
        correct_answer=str(solution.get("answer_latex") or solution.get("answer_value") or "") or None,
        grader="kernel",
        meta={"tool": "geometry.solid", "fingerprint": solution.get("fingerprint")},
    )
    return {
        "query_type": solution["query_type"],
        "title": solution["title"],
        "answer_latex": solution["answer_latex"],
        "answer_value": solution["answer_value"],
        "answer_label": solution["answer_label"],
        "steps": solution["steps"],
        "lesson_data": solution["lesson_data"],
        "fingerprint": solution["fingerprint"],
    }


@router.post("/lesson", response_class=HTMLResponse)
async def solid_geometry_lesson_page(
    spec: SolidGeometrySpec,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    try:
        solution = await solve(spec)
    except SolidGeometryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HTMLResponse(render_lesson_html(solution["lesson_data"]))

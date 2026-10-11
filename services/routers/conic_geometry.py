"""解析几何（圆锥曲线弦问题）路由。

- ``POST /v1/geometry/conic/solve``  → 精确范围/定值 + 分步解析 + 画板数据（JSON）
- ``POST /v1/geometry/conic/lesson`` → 自包含交互画板页面（HTML）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from oprim.conic_analysis import AnalyticGeometrySpec

from services.auth_deps import get_current_user
from services.conic_geometry_service import render_board_html, solve
from services.edu_lesson_common import EduKernelError
from services.models import User

router = APIRouter(prefix="/v1/geometry/conic", tags=["geometry"])

_FIELDS = (
    "target",
    "answer_kind",
    "answer_latex",
    "answer_label",
    "answer_lo",
    "answer_hi",
    "constant_value",
    "title",
    "problem_html",
    "expression_latex",
    "steps",
    "board_data",
    "fingerprint",
)


async def _solve(spec: AnalyticGeometrySpec) -> dict[str, Any]:
    try:
        return await solve(spec)
    except EduKernelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/solve")
async def solve_conic_chord(
    spec: AnalyticGeometrySpec,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    solution = await _solve(spec)
    return {k: solution[k] for k in _FIELDS}


@router.post("/lesson", response_class=HTMLResponse)
async def conic_chord_lesson_page(
    spec: AnalyticGeometrySpec,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    solution = await _solve(spec)
    return HTMLResponse(render_board_html(solution["board_data"]))

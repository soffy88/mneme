"""化学方程式配平路由。

- ``POST /v1/chemistry/equation/balance`` → 系数、配平方程（LaTeX/Unicode）、守恒表、
  摩尔质量、分步解析（JSON）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from oprim.chemical_equation import ReactionSpec

from services.auth_deps import get_current_user
from services.chemical_equation_service import balance
from services.edu_lesson_common import EduKernelError
from services.models import User

router = APIRouter(prefix="/v1/chemistry/equation", tags=["chemistry"])


@router.post("/balance")
async def balance_chemical_equation(
    spec: ReactionSpec,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        solution = await balance(spec)
    except EduKernelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        k: solution[k]
        for k in (
            "reactants",
            "products",
            "coefficients",
            "equation_latex",
            "equation_text",
            "conservation",
            "molar_masses",
            "title",
            "steps",
            "fingerprint",
        )
    }

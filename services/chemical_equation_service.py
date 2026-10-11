"""化学方程式配平（Layer 4）。

调用 3O 事务 ``omodul.equation_balancing_lesson``（sympy 零空间求最小正整数系数 +
纯整数独立守恒复核）。纯计算、无 DB 写入、不调用 LLM。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omodul.equation_balancing_lesson import (
    EquationBalancingLessonConfig,
    EquationBalancingLessonInput,
    equation_balancing_lesson,
)
from oprim.chemical_equation import ReactionSpec

from services.edu_lesson_common import run_omodul


async def balance(spec: ReactionSpec) -> dict[str, Any]:
    def _fn(tmp: Path) -> dict[str, Any]:
        return equation_balancing_lesson(
            EquationBalancingLessonConfig(write_lesson_json=False),
            EquationBalancingLessonInput(spec=spec),
            tmp,
        )

    return await run_omodul(_fn, prefix="mneme-chem-")

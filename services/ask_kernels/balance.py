"""化学方程式配平：从题面里找出方程式，复用既有精确内核（services.chemical_equation_service.balance）。"""

from __future__ import annotations

import re
from typing import Optional

from services.ask_kernels.core import KernelSolution

_FULL2HALF = str.maketrans(
    "０１２３４５６７８９＋－＝（）．，：／ｘｙ",
    "0123456789+-=().,:/xy",
)

_CHEM = re.compile(
    r"((?:\d*[A-Z][a-z]?\d*(?:\([A-Za-z0-9]+\)\d*)*\s*\+\s*)*\d*[A-Z][a-z]?[A-Za-z0-9()]*)\s*"
    r"(?:=|→|->|⟶|——|==|＝)\s*"
    r"((?:\d*[A-Z][a-z]?[A-Za-z0-9()]*\s*\+\s*)*\d*[A-Z][a-z]?[A-Za-z0-9()]*)"
)
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def find_chemical_equation(text: str) -> Optional[str]:
    s = (text or "").translate(_SUBSCRIPTS).translate(_FULL2HALF)
    m = _CHEM.search(s)
    if not m:
        return None
    left, right = m.group(1), m.group(2)
    # 至少一侧有两种物质、且含化学式特征（大写字母开头）
    if "+" not in left and "+" not in right:
        return None
    strip_coef = lambda side: [re.sub(r"^\d+", "", p.strip()) for p in side.split("+") if p.strip()]  # noqa: E731
    return " + ".join(strip_coef(left)) + " = " + " + ".join(strip_coef(right))


async def solve_chemistry_text(text: str) -> Optional[KernelSolution]:
    eq = find_chemical_equation(text)
    if not eq:
        return None
    try:
        from oprim.chemical_equation import ReactionSpec

        from services.chemical_equation_service import balance

        spec = ReactionSpec.from_equation(eq)
        sol = await balance(spec)
    except Exception:  # noqa: BLE001 — 不是合法方程式就交回 LLM
        return None
    steps_raw = sol.get("steps") or []
    steps: list[str] = []
    for st in steps_raw:
        if isinstance(st, dict):
            steps.append(str(st.get("text") or st.get("description") or st.get("title") or "").strip())
        else:
            steps.append(str(st))
    steps = [s for s in steps if s][:8]
    answer = str(sol.get("equation_text") or "")
    if not answer:
        return None
    steps.append(f"配平结果：{answer}")
    return KernelSolution(
        kernel="chemistry.balance",
        answer=answer,
        steps=steps,
        hint="配平的关键：反应前后每种元素的原子个数相等。可以从只出现在一种反应物和一种生成物里的元素开始配。",
        explanation="化学方程式配平（原子守恒），系数取最小正整数。",
    )


__all__ = ["find_chemical_equation", "solve_chemistry_text"]

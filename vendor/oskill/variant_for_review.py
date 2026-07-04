"""复习变式生成 (oskill_variant_for_review)

职责：复习时按知识点出变式题而非原题（变式检索 > 普通间隔重复）。

2026-07-04 修复死代码：此前只调 generate_variant（1 个 oprim），其 answer/
kernel_verified 被永久强制清空/False，导致下游"只有 kernel_verified 才展示变式"
的判断从未为真，静默恒等降级为同题复现。现补上真实核验——独立调 sibling oskill
solve_and_visualize（stateless，深度1，符合 oskill 受限互调约束）对 LLM 提议的
expression 求解；求解成功才把 item.kernel_verified/answer 置为内核结果，否则维持
原样（unsolvable 时行为与修复前一致，不引入新的失败模式）。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, List, Optional
from oprim.generate_variant import generate_variant, VariantInput, VariantItem


@dataclass(frozen=True)
class ReviewVariantInput:
    student_id: str
    kc_id: str
    original_question: str  # 到期的那道原题
    original_answer: str
    variant_type: str = "same_structure"


async def variant_for_review(
    inp: ReviewVariantInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> VariantItem:
    """为复习生成变式，并独立核验（LLM 提议的 answer/expression 均不受信任）。"""

    # 直接调用 generate_variant
    v_inp = VariantInput(
        original_question=inp.original_question,
        original_answer=inp.original_answer,
        kc_ids=[inp.kc_id],
        variant_type=inp.variant_type,
    )

    result = await generate_variant(v_inp, caller=caller, model=model)

    # 独立核验：LLM 只提议 expression（未受信），真答案由 sympy 内核独立求出。
    # expression 为空/求解失败/所装 generate_variant 版本没有该字段（getattr 兜底）
    # → 维持 kernel_verified=False（同修复前行为，安全降级）。
    expression = getattr(result, "expression", "")
    if result.success and expression:
        try:
            from oskill.solve_and_visualize import (
                solve_and_visualize,
                SolveAndVisualizeInput,
            )

            solved = solve_and_visualize(
                SolveAndVisualizeInput(
                    expression=expression,
                    problem_type="auto",
                    generate_svg=False,
                )
            )
            if solved.solvable and solved.solve_answer:
                result.answer = solved.solve_answer
                result.kernel_verified = True
        except Exception:
            pass  # 求解失败/表达式不合法 → 保持未核验，降级同题复现，不抛错

    return result


__version__ = "0.2.0"  # 修死代码：接线独立核验（2026-07-04）

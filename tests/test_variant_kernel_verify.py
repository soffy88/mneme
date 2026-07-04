"""variant_for_review 死代码修复验证（U.17 前置）

修复前：generate_variant 强制 answer=""/kernel_verified=False，且从无任何调用方
补做求解验证，导致所有"只有 kernel_verified 才展示变式"的判断恒为假、静默降级
同题复现。修复：variant_for_review 独立调 solve_and_visualize 对 LLM 提议的
expression 求解，求解成功才置信。
"""

from __future__ import annotations

import pytest


class _ExprLLM:
    def __init__(self, expression: str, question: str = "求解"):
        self._expression = expression
        self._question = question

    async def __call__(self, **kwargs):
        import json

        return {
            "content": json.dumps(
                {
                    "question": self._question,
                    "expression": self._expression,
                    "answer": "占位（不受信）",
                    "difficulty": "medium",
                    "kc_ids": [],
                },
                ensure_ascii=False,
            ),
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


@pytest.mark.asyncio
async def test_solvable_expression_gets_kernel_verified():
    """内核可解的 expression → kernel_verified=True，answer 来自内核而非 LLM。"""
    from oskill.variant_for_review import variant_for_review, ReviewVariantInput

    caller = _ExprLLM("x**2 - 5*x + 6", question="求函数 f(x)=x²-5x+6 的零点")
    result = await variant_for_review(
        ReviewVariantInput(
            student_id="s1",
            kc_id="GDMATH-FUNC-01",
            original_question="求函数 f(x)=x²-3x+2 的零点",
            original_answer="1, 2",
        ),
        caller=caller,
    )
    assert result.kernel_verified is True
    assert result.answer
    assert result.answer != "占位（不受信）"  # 确认答案来自内核，不是 LLM 提议值


@pytest.mark.asyncio
async def test_empty_expression_stays_unverified():
    """LLM 未给出 expression（如应用题无干净符号形式）→ 保持未核验，安全降级。"""
    from oskill.variant_for_review import variant_for_review, ReviewVariantInput

    caller = _ExprLLM("", question="一批零件抽检问题（应用题，无干净符号形式）")
    result = await variant_for_review(
        ReviewVariantInput(
            student_id="s1",
            kc_id="GDMATH-PROB-01",
            original_question="原题",
            original_answer="原答案",
        ),
        caller=caller,
    )
    assert result.kernel_verified is False
    assert result.answer == ""


@pytest.mark.asyncio
async def test_malformed_expression_does_not_raise():
    """不合法 expression → 求解失败被吞掉，不抛错、不误标已核验。"""
    from oskill.variant_for_review import variant_for_review, ReviewVariantInput

    caller = _ExprLLM("this is not )( valid sympy !!!")
    result = await variant_for_review(
        ReviewVariantInput(
            student_id="s1",
            kc_id="GDMATH-FUNC-01",
            original_question="原题",
            original_answer="原答案",
        ),
        caller=caller,
    )
    assert result.kernel_verified is False

"""Generate a variant of a math question using LLM.

Async, single LLM call.
After the LLM response, the answer field is ALWAYS cleared (forced empty)
and kernel_verified is set to False — the variant must be verified separately.

2026-07-04: added `expression` — an LLM-proposed sympy-parseable symbolic form
of the variant, passed through UNVERIFIED (same untrusted status as `answer`).
Callers that need a real kernel_verified/answer must independently solve
`expression` (see oskill.variant_for_review) — this oprim never verifies its
own output (oprims stay single-call/stateless, no oprim-calls-oprim).

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VariantInput:
    """Input for generating a question variant.

    Attributes
    ----------
    original_question : str
        The original question text.
    original_answer : str
        The original correct answer.
    kc_ids : list[str]
        Knowledge components the question targets.
    variant_type : str
        Type of variant: "same_structure", "harder", "easier", "context_change".
    grade_level : str
        Student grade level.
    subject : str
    system : str | None
    """

    original_question: str
    original_answer: str
    kc_ids: list[str] = field(default_factory=list)
    variant_type: str = "same_structure"
    grade_level: str = "中学"
    subject: str = "math"
    system: str | None = None


@dataclass
class VariantItem:
    """A generated question variant.

    Attributes
    ----------
    question : str
        The variant question text.
    answer : str
        Answer — ALWAYS empty after generation (cleared by this element).
        Must be solved/verified by the kernel before use.
    kernel_verified : bool
        Always False after generation — must be set True by kernel after solving.
    kc_ids : list[str]
    difficulty : str
        "easy"/"medium"/"hard"
    variant_type : str
    success : bool
    error : str
    expression : str
        LLM-proposed sympy-parseable symbolic form of the variant (e.g.
        "x**2 - 5*x + 6 < 0"), for a caller to independently kernel-verify.
        UNVERIFIED — same untrusted status as `answer`; empty if the LLM
        didn't provide one or the question has no clean symbolic form.
    """

    question: str = ""
    answer: str = ""
    kernel_verified: bool = False
    kc_ids: list[str] = field(default_factory=list)
    difficulty: str = "medium"
    variant_type: str = "same_structure"
    success: bool = True
    error: str = ""
    expression: str = ""


_VARIANT_SYSTEM = (
    "You are a math question generator. Create a variant of the given math question "
    "that tests the same knowledge components but uses different numbers, contexts, "
    "or slightly different structures. "
    'Return JSON: {"question": str, "answer": str, "expression": str, '
    '"difficulty": "easy|medium|hard", "kc_ids": [str]}. '
    '"expression" is a clean sympy-parseable symbolic form of the question '
    '(e.g. "x**2 - 5*x + 6 < 0"), leave it empty if the question has no such '
    "clean symbolic form (e.g. word problems without a single equation). "
    "The answer field will be discarded for verification purposes; expression "
    "will be independently solved by a symbolic kernel, not trusted from you either."
)


async def generate_variant(
    inp: VariantInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> VariantItem:
    """Generate a question variant using an LLM.

    The returned VariantItem.answer is ALWAYS forced to empty string and
    kernel_verified is ALWAYS False, regardless of what the LLM returns.

    Parameters
    ----------
    inp : VariantInput
    caller : Any
    model : str
    max_tokens : int

    Returns
    -------
    VariantItem
        With answer="" and kernel_verified=False (forced).
    """
    from oprim.llm._llm_complete import llm_complete

    system = inp.system or _VARIANT_SYSTEM

    prompt = (
        f"原题: {inp.original_question}\n"
        f"原答案 (仅供参考): {inp.original_answer}\n"
        f"变式类型: {inp.variant_type}\n"
        f"知识点: {', '.join(inp.kc_ids)}\n"
        f"年级: {inp.grade_level}, 科目: {inp.subject}\n"
        "请生成一道变式题，返回 JSON。"
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")

        data = json.loads(raw)
        item = VariantItem(
            question=data.get("question", ""),
            answer="",  # 强制清空，不论 LLM 返回什么
            kernel_verified=False,  # 强制
            kc_ids=data.get("kc_ids", inp.kc_ids),
            difficulty=data.get("difficulty", "medium"),
            variant_type=inp.variant_type,
            success=True,
            expression=data.get("expression", ""),  # 同样未受信，交调用方独立核验
        )
        return item

    except Exception as exc:
        return VariantItem(
            answer="",  # 强制清空
            kernel_verified=False,  # 强制
            success=False,
            error=str(exc),
        )

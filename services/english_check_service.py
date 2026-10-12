"""英语作答确定性批改（Layer 4）。

调用 3O ``oskill.english_answer_check_skill``（oprim.english_grading 答案等价 / 听写评分 /
句型使用 + oprim.english_pronoun he/she 指代检查）。纯计算、无 DB 写入、不调用 LLM。

另提供 :func:`english_equivalent_answer` 给既有确定性判分路径（mcp_router
``tool_submit_answer``）做缩写感知的英语等价补判：只会把“英语上等价”的作答从错改对，
受 ``MNEME_ENGLISH_ANSWER_FORMS`` 开关控制（默认开，设 0/false/off 关闭）。

代码派生自 recepyagmur/EnglishPractice（MIT），许可见 services/assets/english_grading/。
"""

from __future__ import annotations

import os
import re
from typing import Any

from oprim.english_grading import english_answers_equivalent
from oskill.english_answer_check_skill import EnglishCheckRequest, check_english_answer

FLAG = "MNEME_ENGLISH_ANSWER_FORMS"

# 只对“看起来是英语句子 / 短语”的期望答案补判：拉丁字母、数字、空白与常见标点。
_ENGLISH_CHARS = re.compile(r"^[A-Za-z0-9\s'’‘,.!?\"“”\-]+$")
_ALPHA_WORD = re.compile(r"[A-Za-z]{2,}")
# 数学记号词：含这些词的期望答案留给 sympy 判，不做英语等价。
_MATH_WORDS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "log",
        "ln",
        "lg",
        "lim",
        "sqrt",
        "pi",
        "exp",
    }
)


def english_answer_forms_enabled() -> bool:
    return os.getenv(FLAG, "1").strip().lower() not in {"0", "false", "off", "no"}


def looks_english(text: str) -> bool:
    """期望答案是否像英语：仅拉丁字符，且含缩写撇号或 ≥2 个 ≥2 字母的词，且无数学函数词。"""
    value = (text or "").strip()
    if not value or len(value) > 200 or not _ENGLISH_CHARS.match(value):
        return False
    words = _ALPHA_WORD.findall(value)
    if any(w.lower() in _MATH_WORDS for w in words):
        return False
    has_contraction = bool(re.search(r"[A-Za-z]['’][A-Za-z]", value))
    return has_contraction or len(words) >= 2


def english_equivalent_answer(answer: str, expected: str) -> bool:
    """作答与期望答案在英语上是否等价（缩写感知）。开关关闭或非英语题时恒 False。"""
    if not english_answer_forms_enabled():
        return False
    if (
        not looks_english(expected)
        or not answer
        or not _ENGLISH_CHARS.match(answer.strip())
    ):
        return False
    try:
        return english_answers_equivalent(answer, accepted=[expected], mode="fill").ok
    except ValueError:
        return False


def check(request: EnglishCheckRequest) -> dict[str, Any]:
    """批改一条英语作答，返回可 JSON 序列化的结论。"""
    return check_english_answer(request).model_dump(mode="json")

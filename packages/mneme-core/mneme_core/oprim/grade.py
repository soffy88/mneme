"""mneme-core grade — deterministic objective grading (choice / short / fill).

Pure functions, no IO. 只处理**非数学客观题**：
  - choice / fill → 归一化精确比对
  - short        → SequenceMatcher ≥ SHORT_MATCH_THRESHOLD 模糊比对
数学 solve/fill 由服务层路由到 sympy 内核，**绝不进本模块**（决策 D2.1）；
open（自我解释/作文）交 qualitative_verifier —— 传进来一律 raise（护栏第一道闸）。
归一化用 NFKC 折叠全半角（决策 D3.5）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

# short 模糊比对阈值（决策 D2.1）
SHORT_MATCH_THRESHOLD = 0.85

# answer_match 的合法 qtype 域（决策 D3.5：在 SPEC 原 choice/short 上扩 fill）
Qtype = Literal["choice", "short", "fill"]


@dataclass(frozen=True)
class GradeResult:
    """Immutable result of a deterministic grading operation."""

    is_correct: bool
    score: float  # 0.0 or 1.0 for deterministic grading
    matched: str  # the normalised form that was compared


def _normalise(text: str) -> str:
    """NFKC 折叠全半角 → 小写 → 去首尾空白 → 折叠内部空白 → 去首尾标点。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(".,;:!?\"'")
    return text


def answer_match(answer: str, *, expected: str, qtype: Qtype) -> GradeResult:
    """非数学客观题的确定性比对（determinism 层护栏，mock LLM 给错值也不采信）。

    Args:
        answer: 学生原始作答。
        expected: 标准答案。
        qtype: ``"choice"`` / ``"fill"``（归一化精确）或 ``"short"``（≥0.85 模糊）。

    Returns:
        binary ``GradeResult``（score 1.0/0.0）。

    Raises:
        ValueError: qtype 不在 {choice, short, fill}（含 open / 数学 solve）——
            这些不该走确定性字符串比对，是护栏第一道闸。
    """
    norm_answer = _normalise(answer)
    norm_expected = _normalise(expected)

    if qtype in ("choice", "fill"):
        is_correct = norm_answer == norm_expected
    elif qtype == "short":
        ratio = SequenceMatcher(None, norm_answer, norm_expected).ratio()
        is_correct = ratio >= SHORT_MATCH_THRESHOLD
    else:
        raise ValueError(
            f"answer_match 只接受 choice/short/fill；qtype={qtype!r} "
            "（open 走 qualitative_verifier，数学 solve/fill 走 sympy）"
        )

    return GradeResult(
        is_correct=is_correct,
        score=1.0 if is_correct else 0.0,
        matched=norm_answer,
    )


def grade_objective(answer: str, expected: str, qtype: str) -> GradeResult:
    """DEPRECATED 兼容委托 → :func:`answer_match`（单源：canonical 为 answer_match）。

    保留旧位置参数签名，供既有 grading_service/tools 调用不破；新代码请直接用 answer_match。
    """
    return answer_match(answer, expected=expected, qtype=qtype)  # type: ignore[arg-type]

"""
英语作答确定性批改 Skill（oskill 层）
=====================================

组合 ≥2 个 oprim 原语，把一条英语作答批改成结构化结论：
- 答案等价（缩写感知：'s = is / has、'd = would / had；连词成句忽略句中标点）
- 听写按词评分（漏撇号容错，≤1 处失误全对）
- he / she 指代检查（中文“他 / 她”同音 tā 的典型错误）+ 改正后的句子
- 目标句型是否用上（词可屈折、可插词）

全部结论来自 oprim 的确定性计算，不调用 LLM。

依赖 oprim 原语：
- oprim.english_grading：english_answers_equivalent / score_dictation_words /
  english_answer_forms / uses_pattern / pattern_fixed_parts
- oprim.english_pronoun：find_pronoun_errors / apply_pronoun_fixes

无状态、无 IO，同步函数。

来源：判分思路派生自 recepyagmur/EnglishPractice（app/backend/exams.py、patterns.py、
pronoun_check.py，commit 040d95546f7ffa1ef439ee66f9e8a3cbc7323072，MIT License，
Copyright (c) 2026 recepyagmur；完整许可见 oprim/english_grading.py）。只移植代码逻辑，
未复制其内容数据。
"""

from __future__ import annotations

from oprim.english_grading import (
    AnswerMode,
    DictationScore,
    english_answer_forms,
    english_answers_equivalent,
    pattern_fixed_parts,
    score_dictation_words,
    uses_pattern,
)
from oprim.english_pronoun import PronounError, apply_pronoun_fixes, find_pronoun_errors
from pydantic import BaseModel, ConfigDict, Field, model_validator

KERNEL_VERSION = "english-answer-check/1.0.0"


class EnglishCheckRequest(BaseModel):
    """一条待批改的英语作答。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=2000)  # 学生作答
    accepted: list[str] = Field(
        default_factory=list, max_length=50
    )  # 参考答案（可空：只做指代 / 句型检查）
    type: AnswerMode = "fill"
    context: str = Field(default="", max_length=4000)  # 题干 / 上文，用于 he/she 指代
    pattern: str | None = Field(default=None, max_length=200)  # 目标句型，如 "put ___ off"
    check_pronouns: bool = True  # 听写题恒不做指代检查

    @model_validator(mode="after")
    def _non_empty_accepted(self) -> EnglishCheckRequest:
        if any(not a.strip() for a in self.accepted):
            raise ValueError("参考答案不能为空字符串")
        if any(len(a) > 2000 for a in self.accepted):
            raise ValueError("参考答案过长")
        return self


class EnglishCheckVerdict(BaseModel):
    """确定性批改结论（可 JSON 序列化）。"""

    ok: bool  # 所有适用检查都通过
    type: AnswerMode
    answer_checked: bool  # 是否给了参考答案
    answer_ok: bool | None  # 无参考答案时为 None
    matched_answer: str | None
    normalized_forms: list[str]  # 作答的规范化读法
    dictation: DictationScore | None  # 仅 type=dictation
    dictation_edits: int | None
    pronoun_errors: list[PronounError]
    corrected_text: str  # 应用代词改正后的作答（无错误时等于原文）
    pattern: str | None
    pattern_fixed_parts: list[str]
    pattern_used: bool | None  # 未给句型时为 None
    messages: list[str]  # 中文反馈
    kernel_version: str = KERNEL_VERSION


def check_english_answer(request: EnglishCheckRequest) -> EnglishCheckVerdict:
    """确定性批改一条英语作答（答案等价 + 听写评分 + he/she 指代 + 句型使用）。

    纯算法、stateless、不持久化，故为同步函数。参数非法时抛 ``ValueError``（中文原因）。
    """
    text = request.text
    mode = request.type
    messages: list[str] = []

    answer_ok: bool | None = None
    matched: str | None = None
    dictation: DictationScore | None = None
    if mode == "dictation":
        normalized = english_answer_forms(text, mode="fill") if text.strip() else []
    else:
        normalized = english_answer_forms(text, mode=mode) if text.strip() else []

    if request.accepted:
        if mode == "dictation":
            scores = [score_dictation_words(text, expected=a) for a in request.accepted]
            best = max(range(len(scores)), key=lambda i: (scores[i].score, -scores[i].edits))
            dictation = scores[best]
            answer_ok = dictation.ok
            matched = request.accepted[best] if dictation.ok else None
            if not dictation.given_words:
                messages.append("没有写听写内容。")
            elif dictation.edits == 0:
                messages.append("听写完全正确。")
            elif dictation.ok:
                messages.append("听写正确（有 1 处小失误，不扣分）。")
            else:
                messages.append(f"听写有 {dictation.edits} 处词错误（多写 / 漏写 / 写错）。")
        else:
            eq = english_answers_equivalent(text, accepted=request.accepted, mode=mode)
            answer_ok = eq.ok
            matched = eq.matched_answer
            if not text.strip():
                messages.append("没有作答。")
            elif eq.ok:
                messages.append("答案正确。")
            else:
                messages.append("答案与参考答案不一致。")

    errors: list[PronounError] = []
    if request.check_pronouns and mode != "dictation" and text.strip():
        errors = find_pronoun_errors(text, context=request.context)
    corrected = apply_pronoun_fixes(text, errors=errors) if errors else text
    for e in errors:
        messages.append(f"“{e.wrong}” → “{e.right}”：{e.explanation}")

    fixed: list[str] = []
    used: bool | None = None
    if request.pattern:
        fixed = pattern_fixed_parts(request.pattern)
        used = uses_pattern(text, pattern=request.pattern) if text.strip() else False
        messages.append(
            f"用上了句型 “{request.pattern}”。"
            if used
            else f"句子里没有用到句型 “{request.pattern}”。"
        )

    ok = (answer_ok is not False) and not errors and (used is not False)
    if answer_ok is None and not errors and used is None:
        ok = bool(text.strip())

    return EnglishCheckVerdict(
        ok=ok,
        type=mode,
        answer_checked=bool(request.accepted),
        answer_ok=answer_ok,
        matched_answer=matched,
        normalized_forms=normalized,
        dictation=dictation,
        dictation_edits=dictation.edits if dictation is not None else None,
        pronoun_errors=errors,
        corrected_text=corrected,
        pattern=request.pattern,
        pattern_fixed_parts=fixed,
        pattern_used=used,
        messages=messages,
    )

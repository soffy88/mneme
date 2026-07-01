"""
LLM / Vision 单调用 oprim
=========================
oprim/llm_oprims.py
"""

from __future__ import annotations
import json
from typing import List, Dict, Any, Literal, Optional
from pydantic import BaseModel

from obase.provider_registry import ProviderRegistry
from oprim.types import SolveResult, GradeResult

# ── §5.1 ocr_paper ───────────────────────────────────────────────────────────

class PaperOCRResult(BaseModel):
    questions: List[Dict[str, Any]]  # [{no, question_text, student_answer, correct_answer, subject}]
    raw_text: str

async def ocr_paper(*, image_b64: str, subject: str = "math") -> PaperOCRResult:
    """单 Vision 调用：试卷图片 → 结构化题目列表。"""
    vlm = ProviderRegistry.get().vlm()
    prompt = _OCR_PROMPT.format(subject=subject)
    
    response = await vlm(prompt=prompt, image_b64=image_b64, response_format="json")
    
    content = response.get("content", {})
    if not isinstance(content, dict):
        return PaperOCRResult(questions=[], raw_text=response.get("raw_text", ""))
        
    questions = content.get("questions", [])
    for q in questions:
        if not q.get("question_text"):
            q["question_text"] = "[OCR失败]"
            
    return PaperOCRResult(
        questions=questions,
        raw_text=response.get("raw_text", "")
    )

_OCR_PROMPT = """
你是一个专业的试卷 OCR 系统。分析图片中的{subject}试卷，提取每道题目。
严格返回 JSON，结构：
{{"questions":[{{"no":"题号","question_text":"题干(LaTeX)","student_answer":"学生答案","correct_answer":"标准答案"}}]}}
无法识别的字段填 "[OCR失败]"，不要遗漏任何题号。
"""

# ── §5.2 grade_question ───────────────────────────────────────────────────────

async def grade_question(
    *,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    kc_id: str | None = None,
    solve_result: SolveResult | None = None,
) -> GradeResult:
    """单题批改（确定性优先）。"""
    
    # 确定性优先：有内核结果且可解，则比对内核答案
    if solve_result and solve_result.solvable:
        # TODO: 更好的 LaTeX 等价性比对
        is_correct = (student_answer.strip() == solve_result.answer.strip())
        return GradeResult(is_correct=is_correct, method="kernel", reason="Kernel verified")
        
    # 否则使用 LLM
    llm = ProviderRegistry.get().llm()
    prompt = f"""
    你是数学老师。判定学生答案是否正确。
    题目：{question_text}
    标准答案：{correct_answer}
    学生答案：{student_answer}
    
    仅返回 JSON: {{"is_correct": bool, "reason": "简短原因"}}
    """
    
    response = await llm(messages=[{"role": "user", "content": prompt}], response_format="json")
    
    try:
        data = json.loads(response["content"])
        return GradeResult(
            is_correct=data.get("is_correct", False),
            method="llm",
            reason=data.get("reason")
        )
    except:
        return GradeResult(is_correct=False, method="llm", reason="LLM Parse Error")

# ── §5.3 profiler_analyze ─────────────────────────────────────────────────────

class ProfilerResult(BaseModel):
    error_type: Literal["conceptual", "transfer", "careless", "logic_break", "dontknow"]
    error_reason: str
    knowledge_points: List[str]
    cognitive_break_point: str
    socratic_questions: List[str]
    mastery_estimate: float
    parent_note: str

async def profiler_analyze(
    *,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    kc_candidates: List[str],
) -> ProfilerResult:
    """单 LLM 调用：错题深度认知分析。"""
    llm = ProviderRegistry.get().llm()
    prompt = _PROFILER_PROMPT.format(
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        kc_candidates=kc_candidates
    )
    
    response = await llm(messages=[{"role": "user", "content": prompt}], response_format="json")
    
    try:
        # 简单清洗 markdown
        raw = response["content"]
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        data = json.loads(raw)
        return ProfilerResult(**data)
    except Exception as e:
        # 异常兜底
        return ProfilerResult(
            error_type="dontknow",
            error_reason=f"Analysis failed: {str(e)}",
            knowledge_points=kc_candidates[:1] if kc_candidates else [],
            cognitive_break_point="Unknown",
            socratic_questions=["你能再读一遍题吗？"],
            mastery_estimate=0.1,
            parent_note="分析遇到一点小问题。"
        )

_PROFILER_PROMPT = """
你是高中教育心理学专家，精通高考考纲。
分析以下错题，输出 JSON，字段：
error_type(conceptual|transfer|careless|logic_break|dontknow)
error_reason(一句话)  knowledge_points(KC ID列表，从候选列表中选最相关的 1-3 个)
cognitive_break_point(推导断点)  socratic_questions(3条追问，不含答案)
mastery_estimate(0.0~1.0)  parent_note(家长能懂的一句话)

题目：{question_text}
学生答案：{student_answer}  正确答案：{correct_answer}
候选KC：{kc_candidates}

严格输出纯 JSON，不含解释文字。
"""

__version__ = "0.2.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "ocr_paper", "layer": "oprim", "summary": "Claude Vision 结构化 OCR"},
        {"name": "grade_question", "layer": "oprim", "summary": "题目批改（确定性优先）"},
        {"name": "profiler_analyze", "layer": "oprim", "summary": "错题深度认知分析"},
    ]
}

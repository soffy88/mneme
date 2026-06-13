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

# ── §5.1 ocr_paper ───────────────────────────────────────────────────────────

class PaperOCRResult(BaseModel):
    questions: List[Dict[str, Any]]  # [{no, question_text, student_answer, correct_answer, subject}]
    raw_text: str

async def ocr_paper(*, image_b64: str, subject: str = "math") -> PaperOCRResult:
    """单 Vision 调用：试卷图片 → 结构化题目列表。
    
    Internal oprim composition:
    - obase.ProviderRegistry.vlm  (VLM API 调用)
    """
    vlm = ProviderRegistry.get().vlm()
    prompt = _OCR_PROMPT.format(subject=subject)
    
    response = await vlm(prompt=prompt, image_b64=image_b64, response_format="json")
    
    content = response.get("content", {})
    if not isinstance(content, dict):
        # 异常兜底
        return PaperOCRResult(questions=[], raw_text=response.get("raw_text", ""))
        
    questions = content.get("questions", [])
    
    # 标注识别失败的题目
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

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "ocr_paper", "layer": "oprim", "summary": "Claude Vision 结构化 OCR"},
        {"name": "PaperOCRResult", "layer": "oprim", "summary": "OCR 结果数据结构"},
    ]
}

"""单步错误分类器 (oprim_error_classify)

职责：将 verify_step 判错的单步推理映射到具体的错误类型。
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any

class ErrorTag(str, Enum):
    CONCEPT_MISUNDERSTANDING = "概念不清"
    CALCULATION_ERROR = "计算失误"
    MISREADING = "审题错"
    LOGIC_JUMP = "步骤跳跃"
    UNCLASSIFIED = "未分类"

@dataclass(frozen=True)
class ErrorClassifyInput:
    """分类输入。

    Attributes
    ----------
    question_context : str
        题目全文或上下文。
    step_description : str
        学生此步的意图/描述。
    before_lhs, before_rhs : str
    after_lhs, after_rhs : str
    verify_suggestion : str
        verify_step 返回的错误详情。
    """
    question_context: str
    step_description: str
    before_lhs: str
    after_lhs: str
    before_rhs: str = "0"
    after_rhs: str = "0"
    verify_suggestion: str = ""

@dataclass(frozen=True)
class ErrorClassifyResult:
    primary_tag: ErrorTag
    secondary_tags: list[str] = None
    reason: str = ""

_CLASSIFY_SYSTEM = (
    "你是一个数学教育专家。根据学生的题目、当前解题步骤及计算校验结果，判断其错误类型。\n"
    "错误类型限定为：\n"
    "1. 概念不清：对定理、公式理解错误（如：(a+b)^2 = a^2 + b^2）。\n"
    "2. 计算失误：纯算术错误、符号弄反但逻辑正确（如：3*5=16，或移项未变号）。\n"
    "3. 审题错：抄错数字、理解错已知条件。\n"
    "4. 步骤跳跃：逻辑不连贯，虽然可能正确但跨度太大导致校验不匹配。\n"
    "输出 JSON：{\"primary_tag\": \"...\", \"secondary_tags\": [...], \"reason\": \"...\"}\n"
    "如果不确定，primary_tag 请填写 '未分类'。"
)

async def error_classify(
    inp: ErrorClassifyInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6"
) -> ErrorClassifyResult:
    """使用 LLM 对错误进行分类。"""
    import json
    from oprim.llm._llm_complete import llm_complete

    user_prompt = (
        f"题目上下文: {inp.question_context}\n"
        f"学生步骤意图: {inp.step_description}\n"
        f"变换前: {inp.before_lhs} = {inp.before_rhs}\n"
        f"变换后: {inp.after_lhs} = {inp.after_rhs}\n"
        f"校验反馈: {inp.verify_suggestion}\n"
    )

    messages = [{"role": "user", "content": user_prompt}]
    
    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=_CLASSIFY_SYSTEM,
            model=model
        )
        
        raw = response.text.strip()
        if "```" in raw:
            # 简单处理 markdown code block
            parts = raw.split("```")
            for part in parts:
                if "primary_tag" in part:
                    raw = part
                    if raw.startswith("json"):
                        raw = raw[4:]
                    break
        
        data = json.loads(raw)
        
        tag_map = {
            "概念不清": ErrorTag.CONCEPT_MISUNDERSTANDING,
            "计算失误": ErrorTag.CALCULATION_ERROR,
            "审题错": ErrorTag.MISREADING,
            "步骤跳跃": ErrorTag.LOGIC_JUMP,
        }
        
        primary = tag_map.get(data.get("primary_tag"), ErrorTag.UNCLASSIFIED)
        
        return ErrorClassifyResult(
            primary_tag=primary,
            secondary_tags=data.get("secondary_tags", []),
            reason=data.get("reason", "")
        )
    except Exception:
        return ErrorClassifyResult(primary_tag=ErrorTag.UNCLASSIFIED)

__version__ = "0.1.0"

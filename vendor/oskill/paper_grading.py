"""
错题批改与入库 oskill
====================
oskill/paper_grading.py

职责：
1. 组合 grade_question 与 profiler_analyze。
2. 将错题持久化到数据库。
"""

from __future__ import annotations
import uuid
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert

from oprim.answer_judge import judge_answer
from oprim.llm_oprims import grade_question, profiler_analyze, GradeResult, ProfilerResult
from services.models import WrongQuestion, ErrorType
from data.guangdong_math_kc import KC_LIST

async def process_single_question(
    *,
    session: AsyncSession,
    student_id: uuid.UUID,
    paper_id: Optional[uuid.UUID],
    question_text: str,
    student_answer: str,
    correct_answer: str,
    subject: str = "math"
) -> dict:
    """
    处理单题批改：判定对错 -> (若错) 认知分析 -> 入库。
    
    Internal oprim composition:
    - oprim.grade_question
    - oprim.profiler_analyze
    """
    
    # 1. 批改（确定性优先红线）：试卷自带标准答案(correct_answer)是真值，
    #    故先用确定性比对 judge_answer（选择题/可规范化短答），只有它 unsure
    #    时才退回 LLM 等价判定——杜绝"可确定性判定的题由 LLM 误判"。
    verdict = judge_answer(student_answer, correct_answer)["verdict"]
    if verdict == "correct":
        return {"status": "correct", "grade_method": "deterministic"}
    if verdict == "wrong":
        grade_method = "deterministic"
    else:  # unsure → 自由作答/长答，退回 LLM 等价判定
        grade_res: GradeResult = await grade_question(
            question_text=question_text,
            student_answer=student_answer,
            correct_answer=correct_answer
        )
        if grade_res.is_correct:
            return {"status": "correct", "grade_method": grade_res.method}
        grade_method = grade_res.method
        
    # 2. 错题分析
    # 获取候选 KC 列表供 LLM 参考 (全量 KC ID)
    kc_candidates = [k["kc_id"] for k in KC_LIST]
    
    profiler_res: ProfilerResult = await profiler_analyze(
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        kc_candidates=kc_candidates
    )
    
    # 3. 错题入库
    wq_id = uuid.uuid4()
    ins_stmt = insert(WrongQuestion).values(
        id=wq_id,
        paper_id=paper_id,
        student_id=student_id,
        subject=subject,
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        knowledge_points={"ids": profiler_res.knowledge_points},
        error_type=ErrorType(profiler_res.error_type),
        profiler_analysis=profiler_res.model_dump(),
        created_at=datetime.now(timezone.utc)
    )
    await session.execute(ins_stmt)
    # 调用方负责 commit 或 session 管理
    
    return {
        "status": "wrong",
        "wq_id": str(wq_id),
        "grade_method": grade_method,
        "error_type": profiler_res.error_type,
        "knowledge_points": profiler_res.knowledge_points,
        "parent_note": profiler_res.parent_note
    }

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "process_single_question", "layer": "oskill", "summary": "批改、分析并存入错题库"},
    ]
}

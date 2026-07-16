"""mcp_router — Phase1 门控内核的 MCP 工具面（架构 A：挂进 mneme app）。

agent 经 HTTP 调这些工具触达掌握度，**自身零 DB 连接**。工具面（Layer4）可调
纯库 mneme-core（is_mastered/next_objective）+ gate_store + 既有 process_interaction。

红线：期望答案（expected）只存 gate.pending_question，**任何工具响应都不外传**。

W1 说明：
- 路由暂不加学生鉴权（agent 是内部可信基础设施，须网络隔离；服务令牌留 W2）。
- NextObjective 暂由请求携带 kc_ids（学习路径）；路径持久化留后续。
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.oprim.grade import answer_match
from mneme_core.oprim.mastery_gate import (
    N_MIN,
    QUALITATIVE_TYPES,
    Z,
    is_mastered,
    next_objective,
)
from mneme_core.oprim.spacing import due_reviews
from mneme_core.service.verdict_guard import GuardRejection, enforce

from obase.db import get_db
from services import gate_store
from services.math_grade import grade_math
from services.models import KnowledgeUnit
from services.progress_assembler import build_learning_progress

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ── 工具逻辑（可脱离 HTTP 直测）─────────────────────────────────────────────


async def tool_next_objective(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_ids: list[str],
    now: Optional[float] = None,
) -> dict:
    """组装 progress → next_objective → 序列化（**绝不含 expected**）。"""
    prog = await build_learning_progress(db, student_id, kc_ids)
    step = next_objective(prog, now=now or time.time())

    resp: dict = {
        "action": step.action.value,
        "kc_id": step.kc_id,
        "kc_name": step.kc_name,
        "kc_type": step.kc_type.value if step.kc_type else None,
        "module_id": step.module_id,
        "has_pending": step.pending_question is not None,
    }
    if step.pending_question is not None:
        pq = step.pending_question
        # 红线：只回 question_id/prompt/qtype，绝不回 expected。
        resp["pending_question"] = {
            "question_id": pq.question_id,
            "prompt": pq.prompt,
            "qtype": pq.qtype,
        }
    if step.review_task is not None:
        resp["review_task"] = {
            "kc_id": step.review_task.knowledge_point_id,
            "due_at": step.review_task.due_at,
            "priority": step.review_task.priority,
        }
    return resp


async def tool_get_kc_info(db: AsyncSession, kc_id: str) -> dict:
    """KC 元数据 + rubric（供 agent 跑 qualitative_verifier）。无此 KC → {error}。"""
    row = (
        await db.execute(
            select(KnowledgeUnit.name, KnowledgeUnit.prerequisites).where(
                KnowledgeUnit.id == kc_id
            )
        )
    ).first()
    if row is None:
        return {"error": "kc not found", "kc_id": kc_id}

    gate_type = await gate_store.resolve_gate_type(db, kc_id)
    rubric = await gate_store.get_rubric(db, kc_id)  # None 则不可 assess（fail-safe）
    return {
        "kc_id": kc_id,
        "name": row.name,
        "gate_type": gate_type,
        "prerequisites": row.prerequisites or [],
        "rubric": rubric,
    }


async def tool_check_mastery(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> dict:
    """单 KC 掌握度快照：p_learned / 下界 / n_obs / is_mastered / fsrs_due。"""
    prog = await build_learning_progress(db, student_id, [kc_id])
    kp = prog.modules[0].knowledge_points[0]
    post = prog.bkt.get(kc_id)
    fsrs = prog.fsrs.get(kc_id)

    lower_bound = 0.0
    if post is not None:
        lower_bound = max(0.0, post.p_learned - Z * post.sigma)

    # gate_type 用 D2.2 词汇（qualitative/quantitative），与 GetKCInfo 一致；
    # 不外泄 mneme-core 内部枚举名（procedure/concept…）。
    gate_type = (
        gate_store.QUALITATIVE
        if kp.type in QUALITATIVE_TYPES
        else gate_store.QUANTITATIVE
    )

    return {
        "kc_id": kc_id,
        "gate_type": gate_type,
        "p_learned": post.p_learned if post else 0.0,
        "p_learned_lower_bound": lower_bound,
        "n_obs": post.n_obs if post else 0,
        "confident": (post.n_obs >= N_MIN) if post else False,
        "is_mastered": is_mastered(prog, kp),
        "fsrs_due": fsrs.due_at if fsrs else None,
    }


async def tool_get_review_queue(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_ids: list[str],
    now: Optional[float] = None,
) -> dict:
    """到期复习队列：assembler 组装 review_queue → `due_reviews` 过滤到期 + 排序。

    排序 = (priority, due_at) 升序：error-linked(priority=1) 先出（V11/§4）。
    复习本已可经 NextObjective 优先级 2 驱动；本工具是便捷只读快照（第 7 工具）。
    """
    prog = await build_learning_progress(db, student_id, kc_ids)
    due = due_reviews(prog.review_queue, now or time.time())
    return {
        "student_id": str(student_id),
        "review_queue": [
            {
                "kc_id": t.knowledge_point_id,
                "due_at": t.due_at,
                "priority": t.priority,
            }
            for t in due
        ],
    }


async def tool_pose_question(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    kc_id: str,
    question_id: str,
    prompt: str,
    expected: Optional[str],
    qtype: str,
) -> dict:
    """登记一道待答题；expected 落 gate.pending_question（永不外传，红线）。"""
    await gate_store.pose_question(
        db,
        question_id=question_id,
        student_id=student_id,
        kc_id=kc_id,
        prompt=prompt,
        expected=expected,
        qtype=qtype,
    )
    return {"ok": True, "question_id": question_id}


async def tool_submit_answer(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    question_id: str,
    answer: str,
    time_spent_seconds: Optional[int] = None,
) -> dict:
    """取 pending → 判分 → guard(origin=core) → 既有 process_interaction → clear。

    判分路由（决策 D2.1）：solve/fill→grade_math(sympy)；choice/short→answer_match；
    open→needs_qualitative（零写入，交 assess→ReportResult）。
    """
    pending = await gate_store.get_pending(
        db, student_id=student_id, question_id=question_id
    )
    if pending is None:
        return {"error": "no pending question", "question_id": question_id}

    qtype = pending["qtype"]
    kc_id = pending["kc_id"]
    expected = pending["expected"] or ""

    if qtype == "open":
        # 定性题不走确定性判分；交 assess → ReportResult(llm_verified)
        return {
            "needs_qualitative": True,
            "kc_id": kc_id,
            "question_id": question_id,
        }

    if qtype in ("solve", "fill"):
        is_correct = grade_math(answer, expected)
    elif qtype in ("choice", "short"):
        is_correct = answer_match(answer, expected=expected, qtype=qtype).is_correct
    else:
        return {"error": f"unsupported qtype: {qtype}"}

    # guard：确定性判分由 core 产出（origin=core），杜绝 agent 伪造 deterministic
    enforce("deterministic", None, origin="core")

    # 写既有真相源（BKT/FSRS/kc_mastery/interaction_events），满足 DoD 铁律
    from services.cognitive_service import process_interaction

    await process_interaction(
        db,
        student_id=student_id,
        kc_id=kc_id,
        is_correct=is_correct,
        question_type=qtype,
        source="quick",
        student_answer=answer,
        correct_answer=expected,
        time_spent_seconds=time_spent_seconds,
    )
    await gate_store.clear_pending(db, student_id=student_id, question_id=question_id)
    return {
        "graded": True,
        "is_correct": is_correct,
        "verdict_source": "deterministic",
        "kc_id": kc_id,
    }


async def tool_report_result(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    kc_id: str,
    question_id: Optional[str],
    is_correct: bool,
    verdict_source: str,
    evidence: Optional[dict] = None,
    response_time_ms: Optional[int] = None,
    model_id: Optional[str] = None,
) -> dict:
    """agent 上报裁决（定性主路径）。guard 先于任何写；按 gate_type 分流落库。

    - guard(origin=agent)：agent 不得 deterministic；llm_verified 必须带 evidence。
    - llm_verified → 落 gate.evidence 得 evidence_ref。
    - qualitative KC → upsert gate.qualitative_mastery；quantitative KC → 既有 process_interaction。
    """
    # llm_verified 必须带 evidence 内容（DoD：无 evidence 的 llm_verified 被拒）——
    # 在生成 evidence_ref / 任何写入之前判，保证零写入。
    if verdict_source == "llm_verified":
        if not evidence:
            raise GuardRejection("llm_verified 必须包含 evidence")
        evidence_ref: Optional[str] = uuid.uuid4().hex
    else:
        evidence_ref = None

    # 三拒（含 agent+deterministic 拒绝、source 合法性、llm_verified 需 evidence_ref）
    enforce(verdict_source, evidence_ref, origin="agent")

    if verdict_source == "llm_verified":
        await gate_store.save_evidence(
            db,
            evidence_ref=evidence_ref,  # type: ignore[arg-type]
            student_id=student_id,
            kc_id=kc_id,
            verdict=evidence,  # type: ignore[arg-type]
            model_id=model_id,
        )

    gate_type = await gate_store.resolve_gate_type(db, kc_id)
    if gate_type == gate_store.QUALITATIVE:
        await gate_store.upsert_qualitative_mastery(
            db,
            student_id=student_id,
            kc_id=kc_id,
            passed=is_correct,
            evidence_ref=evidence_ref,
        )
    else:
        # 量化 KC 经 LLM 裁决（如确定性 unsure 的短答）→ 既有 process_interaction
        from services.cognitive_service import process_interaction

        await process_interaction(
            db,
            student_id=student_id,
            kc_id=kc_id,
            is_correct=is_correct,
            question_type="open",
            source="quick",
            time_spent_seconds=(response_time_ms // 1000 if response_time_ms else None),
        )

    if question_id:
        await gate_store.clear_pending(
            db, student_id=student_id, question_id=question_id
        )

    return {
        "recorded": True,
        "kc_id": kc_id,
        "gate_type": gate_type,
        "passed": is_correct,
        "evidence_ref": evidence_ref,
    }


# ── HTTP 端点 ───────────────────────────────────────────────────────────────


class NextObjectiveReq(BaseModel):
    student_id: uuid.UUID
    kc_ids: list[str]
    now: Optional[float] = None


class GetKCInfoReq(BaseModel):
    kc_id: str


class GetReviewQueueReq(BaseModel):
    student_id: uuid.UUID
    kc_ids: list[str]
    now: Optional[float] = None


class CheckMasteryReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str


class PoseQuestionReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str
    question_id: str
    prompt: str
    expected: Optional[str] = None
    qtype: str


class SubmitAnswerReq(BaseModel):
    student_id: uuid.UUID
    question_id: str
    answer: str
    time_spent_seconds: Optional[int] = None


class ReportResultReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str
    question_id: Optional[str] = None
    is_correct: bool
    verdict_source: str
    evidence: Optional[dict] = None
    response_time_ms: Optional[int] = None
    model_id: Optional[str] = None


@router.post("/NextObjective")
async def mcp_next_objective(
    req: NextObjectiveReq, db: AsyncSession = Depends(get_db)
) -> dict:
    return await tool_next_objective(db, req.student_id, req.kc_ids, req.now)


@router.post("/GetKCInfo")
async def mcp_get_kc_info(
    req: GetKCInfoReq, db: AsyncSession = Depends(get_db)
) -> dict:
    return await tool_get_kc_info(db, req.kc_id)


@router.post("/CheckMastery")
async def mcp_check_mastery(
    req: CheckMasteryReq, db: AsyncSession = Depends(get_db)
) -> dict:
    return await tool_check_mastery(db, req.student_id, req.kc_id)


@router.post("/GetReviewQueue")
async def mcp_get_review_queue(
    req: GetReviewQueueReq, db: AsyncSession = Depends(get_db)
) -> dict:
    return await tool_get_review_queue(db, req.student_id, req.kc_ids, req.now)


@router.post("/PoseQuestion")
async def mcp_pose_question(
    req: PoseQuestionReq, db: AsyncSession = Depends(get_db)
) -> dict:
    r = await tool_pose_question(
        db,
        student_id=req.student_id,
        kc_id=req.kc_id,
        question_id=req.question_id,
        prompt=req.prompt,
        expected=req.expected,
        qtype=req.qtype,
    )
    await db.commit()
    return r


@router.post("/SubmitAnswer")
async def mcp_submit_answer(
    req: SubmitAnswerReq, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        r = await tool_submit_answer(
            db,
            student_id=req.student_id,
            question_id=req.question_id,
            answer=req.answer,
            time_spent_seconds=req.time_spent_seconds,
        )
        await db.commit()
        return r
    except GuardRejection as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ReportResult")
async def mcp_report_result(
    req: ReportResultReq, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        r = await tool_report_result(
            db,
            student_id=req.student_id,
            kc_id=req.kc_id,
            question_id=req.question_id,
            is_correct=req.is_correct,
            verdict_source=req.verdict_source,
            evidence=req.evidence,
            response_time_ms=req.response_time_ms,
            model_id=req.model_id,
        )
        await db.commit()
        return r
    except GuardRejection as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

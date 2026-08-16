"""学科扩展：作文 / 口语 / 物理引导 / 阅读引导 / 词汇（自 main 拆出）。"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_session_owner,
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
)
from obase.provider_registry import ProviderRegistry
from services.instant_solve_service import get_pg_pool
from services.models import User, UserRole

router = APIRouter(tags=["subjects"])

# ===== §Essay Guide =====

from oskill import EssayGuideInput, essay_guide


class EssayGuideRequest(BaseModel):
    essay_text: str
    grade: str
    essay_type: str


@router.post("/v1/essay/guide")
async def post_essay_guide(
    req: EssayGuideRequest, current_user: User = Depends(get_current_user)
):
    """
    POST /v1/essay/guide
    作文引导批改（不改写，仅引导）。
    """
    caller = None
    if ProviderRegistry._instance:
        try:
            caller = ProviderRegistry.get().llm()
        except Exception:
            caller = None

    res = await essay_guide(
        EssayGuideInput(
            title="Student Essay",
            content=req.essay_text,
            requirements=f"Grade: {req.grade}, Type: {req.essay_type}",
        ),
        caller=caller,
    )

    return {
        "rubric_scores": res.feedback,
        "guidance_questions": res.suggested_questions,
        "is_completed": res.is_completed,
        "answer_leaked": res.answer_leaked,
    }


# ===== §English Speaking Practice =====

from services.models import SpeakingSession
from services.speaking_service import handle_speaking_practice


class SpeakingPracticeRequest(BaseModel):
    topic: str
    target_sentences: str
    grade: str
    ku_id: str | None = None  # T.10：从知识点入口进入时传，供归因更新掌握度


@router.post("/v1/speaking/practice")
async def post_speaking_practice(
    req: SpeakingPracticeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /v1/speaking/practice
    开始英语口语陪练。
    """
    if current_user.role != UserRole.student:
        raise HTTPException(
            status_code=403, detail="Only students can practice speaking"
        )

    pool = await get_pg_pool()
    result = await handle_speaking_practice(
        pool=pool,
        student_id=current_user.id,
        topic=req.topic,
        target_sentences=req.target_sentences,
        grade=req.grade,
        db=db,
        ku_id=req.ku_id,
    )

    if result["status"] == "failed":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", {}).get("message", "Speaking practice failed"),
        )

    return {
        "session_id": result["session_id"],
        "turns": result["turns"],
        "pronunciation_scores": result["pronunciation_scores"],
        "overall_progress": result["overall_progress"],
        "kc_updated": result.get("kc_updated", False),
    }


@router.get("/v1/speaking/history/{student_id}")
async def get_speaking_history(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/speaking/history/{student_id}
    获取学生的口语陪练历史。鉴权：学生本人或绑定家长（原先任意家长可读）。
    """
    await _ensure_student_access(db, current_user, student_id)

    stmt = (
        select(SpeakingSession)
        .where(SpeakingSession.student_id == student_id)
        .order_by(SpeakingSession.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    return [
        {
            "session_id": str(r.id),
            "topic": r.topic,
            "overall_progress": r.overall_progress,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ===== §M.4 受力分析引导（物理）=====

from services.physics_service import (
    end_force_analysis_session,
    force_analysis_message_stream,
    start_force_analysis,
)


@router.post("/v1/physics/force-analysis/start")
async def post_force_analysis_start(
    question_text: str = Query(...),
    ku_id: str | None = Query(
        None, description="T.10：从知识点入口进入时传，供结束时归因更新掌握度"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/force-analysis/start — 开始受力分析引导会话。

    返回开场引导问（苏格拉底式，不含答案/受力图）。
    """
    result = await start_force_analysis(db, question_text, current_user.id, ku_id)
    return result


@router.post("/v1/physics/force-analysis/message")
async def post_force_analysis_message(
    session_id: UUID = Query(...),
    message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/force-analysis/message — 会话中的学生回复（SSE 流式）。

    返回下一个引导问题；equation_ready=true 时可转交 solve_* 列方程。
    仅会话归属学生本人可继续。
    """
    await _ensure_session_owner(db, current_user, session_id)

    async def event_stream():
        async for chunk in force_analysis_message_stream(db, session_id, message):
            yield chunk


    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/physics/force-analysis/{session_id}/end")
async def post_force_analysis_end(
    session_id: UUID,
    outcome: str = Query("partial"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/force-analysis/{session_id}/end — 结束会话（T.10 认知主线接入）。

    outcome: success|partial|failed|abandoned（客户端提示，服务层用 equation_ready
    历史核对，未核实的 success 降级 partial）。仅会话归属学生本人。
    """
    await _ensure_session_owner(db, current_user, session_id)
    result = await end_force_analysis_session(db, session_id, outcome)
    await (
        db.commit()
    )  # end_force_analysis_session 内的 process_interaction 不自己 commit
    return result


# ===== §M.4b 物理概念优先诊断（U.19：FCI式诊断→认知冲突→计算迁移）=====

from services.physics_service import (
    start_concept_diagnosis,
    submit_concept_diagnosis_answer,
)


@router.post("/v1/physics/concept-diagnosis/start")
async def post_concept_diagnosis_start(
    ku_id: str = Query(..., description="必须是物理 KU"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/concept-diagnosis/start — 学习前先诊断是否持有该 KU 常见误解。

    命中已知误解 → 返回 FCI 式二选一诊断题（不下发哪个选项=误解）；
    未命中或非物理 KU → has_candidate=False，客户端应跳过诊断直接进入
    /v1/physics/force-analysis/start 做计算迁移。
    """
    result = await start_concept_diagnosis(db, ku_id, current_user.id)
    return result


@router.post("/v1/physics/concept-diagnosis/{session_id}/submit")
async def post_concept_diagnosis_submit(
    session_id: UUID,
    chosen_option: str = Query(..., pattern="^[ABab]$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/concept-diagnosis/{session_id}/submit — 提交诊断题作答。

    holds_misconception=true 时 remediation 非空（认知冲突/概念重建文本，
    教研预先写好，确定性呈现，不需要 LLM 判分）；不影响 BKT/FSRS 掌握度。
    """
    await _ensure_session_owner(db, current_user, session_id)
    result = await submit_concept_diagnosis_answer(db, session_id, chosen_option)
    return result


# ===== §M.5 阅读理解引导（英语/语文）=====

from services.reading_guide_service import (
    end_reading_guide_session,
    reading_guide_message_stream,
    start_reading_guide,
)


class ReadingGuideStartReq(BaseModel):
    article_text: str
    question: str
    subject: str = "chinese"
    ku_id: str | None = None  # T.10：从知识点入口进入时传


@router.post("/v1/reading/guide/start")
async def post_reading_guide_start(
    body: ReadingGuideStartReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/start — 开始阅读理解引导会话。

    subject: "chinese" 或 "english"。文章正文走 body（可能很长）。返回开场引导问（不含答案）。
    """
    result = await start_reading_guide(
        db, body.article_text, body.question, body.subject, current_user.id, body.ku_id
    )
    return result


@router.post("/v1/reading/guide/message")
async def post_reading_guide_message(
    session_id: UUID = Query(...),
    message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/message — 会话中的学生回复（SSE 流式）。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)

    async def event_stream():
        async for chunk in reading_guide_message_stream(db, session_id, message):
            yield chunk


    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/reading/guide/{session_id}/end")
async def post_reading_guide_end(
    session_id: UUID,
    outcome: str = Query("partial"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/{session_id}/end — 结束会话（T.10 认知主线接入）。

    outcome: success|partial|failed|abandoned（客户端提示，服务层用 located_passage
    历史核对，未核实的 success 降级 partial）。仅会话归属学生本人。
    """
    await _ensure_session_owner(db, current_user, session_id)
    result = await end_reading_guide_session(db, session_id, outcome)
    await (
        db.commit()
    )  # end_reading_guide_session 内的 process_interaction 不自己 commit
    return result


# ===== §M.5b 英语习得型范式：词汇 FSRS + 分级泛读（U.19）=====

from services.graded_reading_service import select_graded_passage
from services.vocab_service import get_due_vocab_reviews, submit_vocab_review


@router.get("/v1/vocab/due")
async def get_vocab_due(
    student_id: UUID = Query(...),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/vocab/due — 取到期复现词 + 补新词。仅学生本人。"""
    _ensure_student_self(current_user, student_id)
    return await get_due_vocab_reviews(db, student_id, limit)


class VocabReviewSubmitReq(BaseModel):
    student_id: UUID
    vocab_id: str
    remembered: bool


@router.post("/v1/vocab/review")
async def post_vocab_review(
    body: VocabReviewSubmitReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/vocab/review — 提交一次词汇闪卡复现（认识/不认识）。仅学生本人。"""
    _ensure_student_self(current_user, body.student_id)
    result = await submit_vocab_review(
        db, body.student_id, body.vocab_id, body.remembered
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/v1/reading/graded-passage")
async def get_graded_passage(
    student_id: UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/reading/graded-passage — 按词汇水平选 i+1 档分级泛读文章。

    素养轨：只做内容分发，不套 BKT/FSRS；理解引导另调既有
    /v1/reading/guide/start（article_text 传本接口返回的 body_text）。
    """
    _ensure_student_self(current_user, student_id)
    result = await select_graded_passage(db, student_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result



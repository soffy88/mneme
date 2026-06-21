from obase.provider_registry import ProviderRegistry
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Form, Response, Request
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from uuid import UUID
import uuid
from typing import Optional
from datetime import datetime, date, timezone
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import shutil
import os
import json

from obase.db import get_db, SessionLocal
from services.logging_config import configure_logging, logger
from obase.prior_provider import PriorProvider
from obase.llm import register_default_providers
from obase.auth import decode_access_token
from omodul.cognitive import InteractionInput
from omodul.auth import SendCodeInput, RegisterStudentInput, LoginInput
import services.auth_service as auth_service
from services.sms import get_sms_provider
from omodul.paper import (
    upload_paper_workflow,
    PaperConfig,
    PaperUploadInput
)
from services.cognitive_service import (
    mastery_overview,
    process_interaction,
    review_queue,
)
from services.alert_service import get_student_alerts, run_alert_checks
from services.mission_service import complete_mission, get_or_create_mission
from services.socratic_service import (
    end_session,
    escape_session,
    socratic_message_stream,
    start_session,
)
from services.seed import seed_bkt_priors
from services.models import (
    InteractionEvent, KCMastery, MasterySnapshot, Paper,
    ParentStudent, SocraticSession, User, UserRole, WrongQuestion,
    TextbookFile, Highlight, ReadingNote,
    Textbook, KnowledgeCluster, KnowledgeUnit,
)
from services.storage import upload_file, download_file, content_type_for
from data.guangdong_math_kc import KC_LIST, get_kc

# ===== §8 认证依赖 =====
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/auth/login", auto_error=False)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    stmt = select(User).where(User.id == uuid.UUID(user_id))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    
    # Initialize obase infrastructure tables
    from obase.config import settings
    from obase.persistence.pool import PgPool
    from obase.error_tag_store import ensure_error_tag_table
    from obase.interaction_history import ensure_interaction_history_table
    
    dsn = settings.DATABASE_URL.replace('+asyncpg', '')
    pool = await PgPool.get_or_create(dsn=dsn)
    await ensure_error_tag_table(pool)
    await ensure_interaction_history_table(pool)
    
    async with SessionLocal() as session:
        await seed_bkt_priors(session)
        await session.commit()
        await PriorProvider.warm_up(session)
    register_default_providers()

    # Register English speaking practice generic callers (real or mock)
    from services.providers.aliyun_pronunciation import AliyunPronunciationCaller

    aliyun_key = settings.ALIYUN_ACCESS_KEY_ID
    aliyun_secret = settings.ALIYUN_ACCESS_KEY_SECRET
    if aliyun_key and aliyun_secret:
        ProviderRegistry.register("pronunciation", "aliyun", 
            AliyunPronunciationCaller(aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY))
        ProviderRegistry.register("pronunciation", "default",
            AliyunPronunciationCaller(aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY))
    else:
        logger.warning("阿里云语音评测未配置，口语陪练功能将使用 mock 评分")
        class MockPronunciationCaller:
            async def __call__(self, *, audio_b64: str, reference_text: str, **kwargs):
                from oprim._mneme_speech_types import PronunciationResult
                return PronunciationResult(
                    overall_score=0.85,
                    fluency_score=0.80,
                    accuracy_score=0.90,
                    word_scores=[]
                )
        ProviderRegistry.register("pronunciation", "aliyun", MockPronunciationCaller())
        ProviderRegistry.register("pronunciation", "default", MockPronunciationCaller())

    class MockASRCaller:
        async def __call__(self, *, audio_b64: str, language: str = "zh", **kwargs):
            return "Yes, this is a mock transcription of the student response."
            
    class MockTTSCaller:
        async def __call__(self, *, text: str, language: str = "en", **kwargs):
            return "dGVzdF9hdWRpb19kYXRh"
            
    ProviderRegistry.register("asr", "default", MockASRCaller())
    ProviderRegistry.register("tts", "default", MockTTSCaller())

    # SMS provider (mock by default, switch to aliyun after 报备)
    import services.main as _self
    _self._sms_provider = get_sms_provider()
    logger.info(f"SMS provider: {type(_self._sms_provider).__name__}")

    yield

_sms_provider = get_sms_provider()  # module-level default; replaced in lifespan

app = FastAPI(title="Mneme API", version="0.1.0", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mneme.uex.hk", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "healthy", "service": "mneme-api"}

# ===== §8 认证 API =====

@app.post("/v1/auth/send-code")
async def post_send_code(payload: SendCodeInput):
    """POST /v1/auth/send-code — 发送短信验证码，存 Redis TTL=5min，60s防刷。"""
    import services.main as _self
    result = await auth_service.send_code(payload.phone, _self._sms_provider)
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["message"])
    return result


@app.post("/v1/auth/register/student", status_code=201)
async def post_register_student(
    payload: RegisterStudentInput,
    db: AsyncSession = Depends(get_db),
):
    """注册学生：Redis验证码校验 + 合规校验 + 写库 + 返回JWT。"""
    result = await auth_service.register_student(
        db=db,
        phone=payload.phone,
        code=payload.code,
        name=payload.name,
        birth_date=payload.birth_date,
        grade=payload.grade,
        guardian_phone=payload.guardian_phone,
        guardian_consent=payload.guardian_consent,
    )
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    await db.commit()
    return result


@app.post("/v1/auth/login")
async def post_login(payload: LoginInput, db: AsyncSession = Depends(get_db)):
    """登录：Redis验证码校验 → JWT。"""
    result = await auth_service.login(db=db, phone=payload.phone, code=payload.code)
    if "error" in result:
        raise HTTPException(status_code=result["error_code"], detail=result["error"])
    return result

@app.get("/v1/auth/me")
async def get_me(
    user: User = Depends(get_current_user)
):
    """获取当前用户信息。"""
    return {
        "id": str(user.id),
        "phone": user.phone,
        "role": user.role.value,
        "name": user.name
    }

# ===== §8 认知状态 API =====

@app.post("/v1/interaction")
async def post_interaction(
    interaction: InteractionInput,
    db: AsyncSession = Depends(get_db)
):
    """POST /v1/interaction — 处理一次答题交互并更新认知状态。"""
    try:
        result = await process_interaction(
            db,
            student_id=interaction.student_id,
            kc_id=interaction.kc_id,
            is_correct=interaction.is_correct,
            question_type=interaction.question_type,
            question_id=interaction.question_id,
            source=interaction.source,
            used_answer=interaction.used_answer,
            struggled=interaction.struggled,
            effortless=interaction.effortless,
            is_interleaved=interaction.is_interleaved,
            time_spent_seconds=interaction.time_spent_seconds,
            now=interaction.now,
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/mastery/curve/{student_id}/{kc_id}")
async def get_mastery_curve(
    student_id: UUID,
    kc_id: str,
    db: AsyncSession = Depends(get_db)
):
    """GET /v1/mastery/curve/{student_id}/{kc_id} — mastery_snapshots 月度时间序列。"""
    rows = (
        await db.execute(
            select(MasterySnapshot)
            .where(MasterySnapshot.student_id == student_id)
            .where(MasterySnapshot.knowledge_point == kc_id)
            .order_by(MasterySnapshot.snapshot_month)
        )
    ).scalars().all()
    return [
        {
            "month": r.snapshot_month.isoformat(),
            "long_term_mastery": round(r.long_term_mastery, 4) if r.long_term_mastery else None,
            "dominant_error_type": r.dominant_error_type,
        }
        for r in rows
    ]

@app.get("/v1/mastery/{student_id}")
async def get_mastery(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """GET /v1/mastery/{student_id} — 掌握度总览（按薄弱排序，含百分位）。"""
    try:
        return await mastery_overview(db, student_id, now=now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/review-queue/{student_id}")
async def get_review_queue(
    student_id: UUID,
    now: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """GET /v1/review-queue/{student_id} — 今日复习队列（interleaved）。"""
    try:
        return await review_queue(db, student_id, now=now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/kc")
async def list_kc():
    """
    GET /v1/kc
    获取全部知识点字典。
    """
    return KC_LIST

@app.get("/v1/kc/{kc_id}")
async def get_kc_detail(kc_id: str):
    """
    GET /v1/kc/{kc_id}
    获取特定知识点详情。
    """
    kc = get_kc(kc_id)
    if not kc:
        raise HTTPException(status_code=404, detail="Knowledge Component not found")
    return kc

# ===== §2b 知识单元接口（DB 版，替代旧 KC 字典）=====

@app.get("/v1/knowledge-points")
async def list_knowledge_points(
    subject: Optional[str] = Query(None),
    textbook_id: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/knowledge-points
    查询知识单元，支持按 subject / textbook_id / cluster_id 筛选。
    返回带 cluster 信息和全部 AII 字段的 KU 列表。
    """
    stmt = select(KnowledgeUnit, KnowledgeCluster, Textbook).join(
        KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id
    ).join(
        Textbook, KnowledgeUnit.textbook_id == Textbook.id
    )
    if subject:
        stmt = stmt.where(Textbook.subject == subject)
    if textbook_id:
        stmt = stmt.where(KnowledgeUnit.textbook_id == textbook_id)
    if cluster_id:
        stmt = stmt.where(KnowledgeUnit.cluster_id == cluster_id)
    stmt = stmt.order_by(KnowledgeCluster.display_order, KnowledgeUnit.id)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id":                  ku.id,
            "name":                ku.name,
            "description":         ku.description,
            "textbook_id":         ku.textbook_id,
            "cluster_id":          ku.cluster_id,
            "cluster_name":        kc.name,
            "cluster_order":       kc.display_order,
            "subject":             tb.subject,
            "grade":               tb.grade,
            "edition":             tb.edition,
            "book_name":           tb.book_name,
            "prerequisites":       ku.prerequisites,
            "related_kus":         ku.related_kus,
            "difficulty":          round(ku.difficulty, 4),
            "exam_frequency":      ku.exam_frequency,
            "question_types":      ku.question_types,
            "ku_type":             ku.ku_type,
            "curriculum_standard": ku.curriculum_standard,
            "mastery_levels":      ku.mastery_levels,
        }
        for ku, kc, tb in rows
    ]


@app.get("/v1/knowledge-points/{ku_id}")
async def get_knowledge_point(
    ku_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/knowledge-points/{ku_id} — 单个 KU 详情。"""
    row = (await db.execute(
        select(KnowledgeUnit, KnowledgeCluster, Textbook).join(
            KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id
        ).join(
            Textbook, KnowledgeUnit.textbook_id == Textbook.id
        ).where(KnowledgeUnit.id == ku_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    ku, kc, tb = row
    return {
        "id":                  ku.id,
        "name":                ku.name,
        "description":         ku.description,
        "textbook_id":         ku.textbook_id,
        "cluster_id":          ku.cluster_id,
        "cluster_name":        kc.name,
        "subject":             tb.subject,
        "grade":               tb.grade,
        "prerequisites":       ku.prerequisites,
        "related_kus":         ku.related_kus,
        "difficulty":          round(ku.difficulty, 4),
        "exam_frequency":      ku.exam_frequency,
        "question_types":      ku.question_types,
        "ku_type":             ku.ku_type,
        "curriculum_standard": ku.curriculum_standard,
        "mastery_levels":      ku.mastery_levels,
    }


# ===== §3 试卷接口 =====

@app.post("/v1/papers/upload")
async def post_paper_upload(
    student_id: UUID = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    POST /v1/papers/upload
    上传一张试卷并启动处理流程。
    """
    config = PaperConfig()
    
    # 临时保存本地
    temp_dir = "/tmp/mneme_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = Path(temp_dir) / f"{uuid.uuid4()}_{file.filename}"
    
    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        payload = PaperUploadInput(
            student_id=student_id,
            local_file_path=local_path,
            filename=file.filename or "unknown.jpg"
        )
        
        result = await upload_paper_workflow(config, payload, db)
        
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result["error"])
            
        return result["findings"]
        
    finally:
        # 清理临时文件
        if local_path.exists():
            os.remove(local_path)


@app.get("/v1/papers/{paper_id}")
async def get_paper(paper_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/papers/{id} — 试卷详情 + 错题 + 共同断点。"""
    paper = (await db.execute(select(Paper).where(Paper.id == paper_id))).scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    wqs = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.paper_id == paper_id)
    )).scalars().all()
    return {
        "paper": {"id": str(paper.id), "student_id": str(paper.student_id),
                  "status": paper.status.value if paper.status else None,
                  "subject": paper.subject, "created_at": paper.created_at.isoformat() if paper.created_at else None},
        "wrong_questions": [{"id": str(w.id), "kc_ids": list((w.knowledge_points or {}).keys()),
                              "error_type": w.error_type.value if w.error_type else None} for w in wqs],
    }


@app.get("/v1/papers")
async def list_papers(
    student_id: UUID = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/papers — 试卷列表。"""
    stmt = select(Paper).where(Paper.student_id == student_id).order_by(Paper.created_at.desc())
    papers = (await db.execute(stmt)).scalars().all()
    return [{"id": str(p.id), "status": p.status.value if p.status else None,
             "subject": p.subject, "created_at": p.created_at.isoformat() if p.created_at else None}
            for p in papers]


# ===== §C.2 多孩子绑定 =====

@app.post("/v1/auth/bind-child")
async def post_bind_child(
    invite_code: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/auth/bind-child — 家长绑定孩子。"""
    student = (await db.execute(
        select(User).where(User.invite_code == invite_code, User.role == UserRole.student)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found with invite code")
    existing = (await db.execute(
        select(ParentStudent)
        .where(ParentStudent.parent_id == current_user.id, ParentStudent.student_id == student.id)
    )).scalar_one_or_none()
    if not existing:
        db.add(ParentStudent(parent_id=current_user.id, student_id=student.id))
        await db.commit()
    return {"ok": True, "student_id": str(student.id), "student_name": student.name}


@app.get("/v1/parent/children")
async def get_children(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/children — 家长的孩子列表。"""
    rows = (await db.execute(
        select(ParentStudent, User)
        .join(User, ParentStudent.student_id == User.id)
        .where(ParentStudent.parent_id == current_user.id)
        .order_by(ParentStudent.display_order)
    )).all()
    return [{"student_id": str(ps.student_id), "name": u.name, "grade": u.grade}
            for ps, u in rows]


# ===== §E.1 今日目标 =====

@app.get("/v1/missions/today/{student_id}")
async def get_today_mission(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/missions/today/{student_id} — 获取或创建今日目标。"""
    try:
        result = await get_or_create_mission(db, student_id)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/missions/{mission_id}/complete")
async def post_complete_mission(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    """POST /v1/missions/{id}/complete — 完成任务，更新 streak。"""
    result = await complete_mission(db, mission_id)
    await db.commit()
    return result


# ===== §E.2 每日学科计划（桩接口） =====

@app.get("/v1/daily-plan/{student_id}")
async def get_daily_plan(
    student_id: UUID,
    subject: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/daily-plan/{student_id}?subject=xxx — 每日学习计划规则引擎。

    subject 不传 → 所有科目汇总（首页用）
    subject=math  → 单科详细（学科页用）

    优先级：P1 FSRS到期 > P2 错题 > P3 薄弱 > P4 新知识点
    """
    from services.daily_plan_service import build_daily_plan
    return await build_daily_plan(db, student_id, subject=subject)


# ===== §F.1 苏格拉底会话 =====

@app.post("/v1/socratic/start")
async def post_socratic_start(
    question_id: UUID = Query(...),
    student_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/start — 开始苏格拉底会话。"""
    result = await start_session(db, question_id, student_id)
    await db.commit()
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/v1/socratic/{session_id}/message")
async def post_socratic_message(
    session_id: UUID,
    student_message: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/{id}/message — SSE 流式苏格拉底回复。"""
    async def event_stream():
        async for chunk in socratic_message_stream(db, session_id, student_message):
            yield chunk
        await db.commit()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/socratic/{session_id}/escape")
async def post_socratic_escape(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """POST /v1/socratic/{id}/escape — 请求答案大纲（非完整答案）。"""
    result = await escape_session(db, session_id)
    await db.commit()
    return result


@app.post("/v1/socratic/{session_id}/end")
async def post_socratic_end(
    session_id: UUID,
    outcome: str = Query("partial"),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/{id}/end — 结束会话，写 outcome。"""
    result = await end_session(db, session_id, outcome)
    await db.commit()
    return result


# ===== §G.1 家长成长摘要 =====

@app.get("/v1/parent/overview/{student_id}")
async def get_parent_overview(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/parent/overview/{student_id} — 学生学习摘要（家长视角）。"""
    rows = (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id))).scalars().all()
    weak_kc = [r for r in rows if (r.p_mastery or 0) < 0.5]
    from services.cognitive_service import _get_streak_dict
    streak = await _get_streak_dict(db, student_id)
    recent_sessions = (await db.execute(
        select(SocraticSession)
        .where(SocraticSession.student_id == student_id)
        .order_by(SocraticSession.created_at.desc()).limit(5)
    )).scalars().all()
    return {
        "weak_kc_count": len(weak_kc),
        "total_kc_practiced": len(rows),
        "streak": streak,
        "recent_sessions": len(recent_sessions),
    }


# ===== §H.1 求解接口 =====

@app.post("/v1/solve")
async def post_solve(kc_id: str = Query(...), expression: str = Query(...)):
    """POST /v1/solve — 调 oskill.solve_and_visualize 确定性求解。"""
    from oskill.solve_and_visualize import SolveAndVisualizeInput, solve_and_visualize
    inp = SolveAndVisualizeInput(expression=expression, problem_type="auto")
    try:
        result = solve_and_visualize(inp)
        return {
            "kc_id": kc_id,
            "answer": result.solve_answer,
            "solvable": result.solvable,
            "steps": result.solve_steps,
            "svg": result.svg,
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


# ===== §H.2 讲解页 =====

@app.get("/v1/lesson/{question_id}")
async def get_lesson(question_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/lesson/{question_id} — 讲解页（缓存优先）。"""
    from services.models import LessonPage
    # Cache check
    cached = (await db.execute(
        select(LessonPage).where(LessonPage.question_id == question_id)
    )).scalar_one_or_none()
    if cached:
        return {"question_id": str(question_id), "plot_data": cached.plot_data,
                "self_check_passed": cached.self_check_passed, "cached": True}
    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == question_id)
    )).scalar_one_or_none()
    if not wq:
        raise HTTPException(status_code=404, detail="Question not found")
    from omodul.generate_lesson_page import LessonPageConfig, LessonPageInput, generate_lesson_page
    import hashlib as _hashlib
    kc_id = next(iter(wq.knowledge_points.keys()), "") if isinstance(wq.knowledge_points, dict) else ""
    question_text = wq.question_text or ""
    question_hash = _hashlib.sha256(question_text.encode()).hexdigest()[:16]
    result = await generate_lesson_page(
        config=LessonPageConfig(kc_id=kc_id, question_hash=question_hash),
        input_data=LessonPageInput(
            question_text=question_text,
            correct_answer=wq.correct_answer or "",
            problem_spec={},
        ),
        output_dir=Path(f"/tmp/mneme/lesson/{question_id}"),
    )
    if result.get("status") == "ok":
        from services.models import LessonPage
        cached_row = LessonPage(
            question_id=question_id,
            fingerprint=result.get("fingerprint", ""),
            plot_data={"svg": result.get("svg", ""), "steps": result.get("steps", [])},
            self_check_passed=result.get("self_check_passed", False),
        )
        db.add(cached_row)
        try:
            await db.flush()
        except Exception:
            await db.rollback()
    return {
        "question_id": str(question_id),
        "plot_data": {"svg": result.get("svg", ""), "steps": result.get("steps", [])},
        "answer": result.get("answer", ""),
        "self_check_passed": result.get("self_check_passed"),
        "status": result.get("status"),
        "cached": False,
    }


# ===== §I.1 变式题 =====

@app.post("/v1/practice/generate")
async def post_practice_generate(
    kc_id: str = Query(...),
    count: int = Query(3),
    difficulty: float = Query(0.5),
    question_type: str = Query("solve"),
    student_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/generate — 生成变式题（调 omodul.practice_workflow）。"""
    from omodul.practice_workflow import PracticeConfig, practice_workflow
    kc = get_kc(kc_id)
    if not kc:
        raise HTTPException(status_code=404, detail="KC not found")
    sid = student_id or uuid.uuid4()
    result = await practice_workflow(
        config=PracticeConfig(
            kc_id=kc_id,
            count=count,
            difficulty=difficulty,
            question_type=question_type,
        ),
        input_data=None,
        output_dir=Path(f"/tmp/mneme/practice/{sid}"),
    )
    items = result.get("items", [])
    return {
        "kc_id": kc_id,
        "kc_name": kc.get("name", kc_id),
        "items": items,
        "status": result.get("status", "ok"),
    }


# ===== §J.1 纵向分析 =====

@app.get("/v1/patterns/{student_id}")
async def get_patterns(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/patterns/{student_id} — 个人学习模式分析。"""
    from oskill.longitudinal_pattern import AttemptRecord, longitudinal_pattern
    events = (await db.execute(
        select(InteractionEvent)
        .where(InteractionEvent.student_id == student_id)
        .order_by(InteractionEvent.occurred_at)
    )).scalars().all()
    records = [
        AttemptRecord(
            question_id=str(e.question_id) if e.question_id else e.knowledge_point,
            kc_id=e.knowledge_point,
            correct=e.is_correct,
            timestamp=e.occurred_at.timestamp() if e.occurred_at else 0.0,
        )
        for e in events
    ]
    if not records:
        return {"patterns": [], "student_id": str(student_id)}
    result = longitudinal_pattern(records)
    return {
        "student_id": str(student_id),
        "improving_kcs": result.improving_kcs,
        "forgetting_kcs": result.forgetting_kcs,
        "plateau_kcs": result.plateau_kcs,
        "overall_trend": round(result.overall_trend, 4),
        "patterns": [
            {"kc_id": t.kc_id, "trend": round(t.trend, 4),
             "current_accuracy": round(t.current_accuracy, 4),
             "is_forgetting": t.is_forgetting, "is_plateau": t.is_plateau}
            for t in result.kc_trajectories.values()
        ],
    }


# ===== §K.1 档案导出 =====

@app.get("/v1/parent/export/{student_id}")
async def get_export(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """GET /v1/parent/export/{student_id} — 导出学生学习档案 JSON。"""
    user = (await db.execute(select(User).where(User.id == student_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    mastery = (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id))).scalars().all()
    events = (await db.execute(
        select(InteractionEvent).where(InteractionEvent.student_id == student_id)
    )).scalars().all()
    archive = {
        "student_id": str(student_id),
        "name": user.name,
        "kc_mastery": [{"kc_id": r.knowledge_point, "p_mastery": round(r.p_mastery or 0, 4)} for r in mastery],
        "interaction_count": len(events),
    }
    content = json.dumps(archive, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=archive_{student_id}.json"},
    )


# ===== §K.2 用户删除（合规） =====

@app.post("/v1/parent/delete-request/{student_id}")
async def post_delete_request(student_id: UUID, db: AsyncSession = Depends(get_db)):
    """POST /v1/parent/delete-request/{student_id} — 软删除学生数据（合规红线）。"""
    user = (await db.execute(select(User).where(User.id == student_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    now = datetime.now(timezone.utc)
    await db.execute(
        update(User).where(User.id == student_id).values(deleted_at=now)
    )
    await db.commit()
    return {"ok": True, "deleted_at": now.isoformat(), "student_id": str(student_id)}


# ===== §G.2 家长预警 =====

@app.get("/v1/parent/alerts/{student_id}")
async def get_alerts(
    student_id: UUID,
    parent_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/alerts/{student_id} — 家长预警列表。"""
    return await get_student_alerts(db, student_id, parent_id)


@app.post("/v1/parent/alerts/{student_id}/check")
async def post_run_alert_checks(
    student_id: UUID,
    parent_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/parent/alerts/{student_id}/check — 立即执行 5 类预警检查。"""
    result = await run_alert_checks(db, student_id, parent_id)
    await db.commit()
    return {"checked": len(result), "alerts": result}


# ===== §D.4 单题快录 =====

@app.post("/v1/papers/quick")
async def post_quick_question(
    student_id: UUID = Query(...),
    kc_hint: Optional[str] = Query(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/papers/quick — 单题快录，立即创建 WrongQuestion。"""
    import uuid as _uuid
    wq_id = _uuid.uuid4()
    wq = WrongQuestion(
        id=wq_id,
        student_id=student_id,
        subject="math",
        knowledge_points={kc_hint: 1.0} if kc_hint else {},
    )
    db.add(wq)
    await db.commit()
    return {"question_id": str(wq_id), "status": "pending_ocr", "kc_hint": kc_hint}


# ===== §L.1 健康检查 =====

@app.get("/health")
async def health_check():
    """GET /health — 服务健康状态。"""
    return {"status": "ok", "version": "0.1.0", "service": "mneme-api"}

# ===== §Instant Solve =====

from fastapi import Form
from services.instant_solve_service import handle_instant_solve, get_pg_pool
import base64

@app.post("/v1/instant-solve")
async def post_instant_solve(
    kc_hint: Optional[str] = Form(None),
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    POST /v1/instant-solve
    随手拍单题（不给答案，苏格拉底引导）。
    """
    image_bytes = await image.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    
    try:
        result = await handle_instant_solve(
            student_id=current_user.id,
            image_b64=image_b64,
            kc_hint=kc_hint
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===== §Review Due Variants =====

from services.review_service import get_due_variants

@app.get("/v1/review/due/{student_id}")
async def get_review_due(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    GET /v1/review/due/{student_id}
    获取到期的变式复习题。
    """
    if student_id != current_user.id and current_user.role != UserRole.parent:
         raise HTTPException(status_code=403, detail="Permission denied")
         
    items = await get_due_variants(db, student_id)
    return items

# ===== §Error Journal =====

from obase.error_tag_store import get_error_distribution
from services.cognitive_service import PgStore

@app.get("/v1/error-journal/{student_id}")
async def get_error_journal(
    student_id: UUID,
    kc_id: Optional[str] = Query(None),
    error_type: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    GET /v1/error-journal/{student_id}
    错题本主动入口。
    """
    if student_id != current_user.id and current_user.role != UserRole.parent:
         raise HTTPException(status_code=403, detail="Permission denied")

    # 1. Get distribution
    pool = await get_pg_pool()
    dist = await get_error_distribution(pool, student_id, kc_id)
    
    # 2. Get detailed wrong questions
    # Layer 4 query
    stmt = select(WrongQuestion).where(WrongQuestion.student_id == student_id)
    if kc_id:
        stmt = stmt.where(WrongQuestion.knowledge_points.has_key(kc_id))
    # Note: error_type filtering would require error_tag join if not in wrong_questions
    
    stmt = stmt.order_by(WrongQuestion.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    
    res = []
    for r in rows:
        res.append({
            "question_id": str(r.id),
            "kc_id": list(r.knowledge_points.keys())[0] if r.knowledge_points else "unknown",
            "error_tag": r.error_type or "unknown",
            "wrong_at": r.created_at.isoformat(),
            "can_practice_variant": True
        })
        
    return {"distribution": dist, "items": res}

# ===== §Essay Guide =====

from oskill import essay_guide, EssayGuideInput

class EssayGuideRequest(BaseModel):
    essay_text: str
    grade: str
    essay_type: str

@app.post("/v1/essay/guide")
async def post_essay_guide(
    req: EssayGuideRequest,
    current_user: User = Depends(get_current_user)
):
    """
    POST /v1/essay/guide
    作文引导批改（不改写，仅引导）。
    """
    caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None
    
    res = await essay_guide(
        EssayGuideInput(
            title="Student Essay",
            content=req.essay_text,
            requirements=f"Grade: {req.grade}, Type: {req.essay_type}"
        ),
        caller=caller
    )
    
    return {
        "rubric_scores": res.feedback,
        "guidance_questions": res.suggested_questions,
        "is_completed": res.is_completed
    }


# ===== §English Speaking Practice =====

from services.speaking_service import handle_speaking_practice
from services.instant_solve_service import get_pg_pool
from services.models import SpeakingSession

class SpeakingPracticeRequest(BaseModel):
    topic: str
    target_sentences: str
    grade: str

@app.post("/v1/speaking/practice")
async def post_speaking_practice(
    req: SpeakingPracticeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    POST /v1/speaking/practice
    开始英语口语陪练。
    """
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Only students can practice speaking")
        
    pool = await get_pg_pool()
    result = await handle_speaking_practice(
        pool=pool,
        student_id=current_user.id,
        topic=req.topic,
        target_sentences=req.target_sentences,
        grade=req.grade
    )
    
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result.get("error", {}).get("message", "Speaking practice failed"))
        
    return {
        "session_id": result["session_id"],
        "turns": result["turns"],
        "pronunciation_scores": result["pronunciation_scores"],
        "overall_progress": result["overall_progress"]
    }

@app.get("/v1/speaking/history/{student_id}")
async def get_speaking_history(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    GET /v1/speaking/history/{student_id}
    获取学生的口语陪练历史。
    """
    # Parent/Student permission check
    if current_user.id != student_id and current_user.role != UserRole.parent:
        raise HTTPException(status_code=403, detail="Permission denied")
        
    stmt = select(SpeakingSession).where(SpeakingSession.student_id == student_id).order_by(SpeakingSession.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    
    return [
        {
            "session_id": str(r.id),
            "topic": r.topic,
            "overall_progress": r.overall_progress,
            "created_at": r.created_at.isoformat()
        }
        for r in rows
    ]


# ===== §M.4 受力分析引导（物理）=====

from services.physics_service import start_force_analysis, force_analysis_message_stream


@app.post("/v1/physics/force-analysis/start")
async def post_force_analysis_start(
    question_text: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/force-analysis/start — 开始受力分析引导会话。

    返回开场引导问（苏格拉底式，不含答案/受力图）。
    """
    result = await start_force_analysis(db, question_text, current_user.id)
    return result


@app.post("/v1/physics/force-analysis/message")
async def post_force_analysis_message(
    session_id: UUID = Query(...),
    message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/physics/force-analysis/message — 会话中的学生回复（SSE 流式）。

    返回下一个引导问题；equation_ready=true 时可转交 solve_* 列方程。
    """
    async def event_stream():
        async for chunk in force_analysis_message_stream(db, session_id, message):
            yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ===== §M.5 阅读理解引导（英语/语文）=====

from services.reading_guide_service import start_reading_guide, reading_guide_message_stream


@app.post("/v1/reading/guide/start")
async def post_reading_guide_start(
    article_text: str = Query(...),
    question: str = Query(...),
    subject: str = Query("chinese"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/start — 开始阅读理解引导会话。

    subject: "chinese" 或 "english"。返回开场引导问（不含答案）。
    """
    result = await start_reading_guide(db, article_text, question, subject, current_user.id)
    return result


@app.post("/v1/reading/guide/message")
async def post_reading_guide_message(
    session_id: UUID = Query(...),
    message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/message — 会话中的学生回复（SSE 流式）。"""
    async def event_stream():
        async for chunk in reading_guide_message_stream(db, session_id, message):
            yield chunk

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ===== §教材阅读器 — 文件/高亮/笔记 =====


def _new_file_id() -> str:
    return str(uuid.uuid4())


def _new_str_id() -> str:
    return str(uuid.uuid4())


# ── 文件上传 ─────────────────────────────────────────────────────────

@app.post("/v1/textbook-files/upload", status_code=201)
async def upload_textbook_file(
    file: UploadFile = File(...),
    textbook_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /v1/textbook-files/upload — 上传教材文件(PDF/EPUB)。
    - 学生上传自己的资料 → owner_student_id = current_user.id
    - 暂不做管理员角色区分，textbook_id 由调用方传入（平台预置时传，自传时不传）
    """
    filename = file.filename or "untitled"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "epub"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 EPUB 文件")

    data = await file.read()
    file_id = _new_file_id()
    # 平台预置：textbook_id 有值、owner 为空；学生自传：owner 有值
    is_platform = textbook_id is not None and current_user.role == UserRole.parent
    owner_id = None if is_platform else current_user.id
    storage_path = f"{'platform' if is_platform else str(current_user.id)}/{file_id}.{ext}"

    await asyncio.to_thread(upload_file, storage_path, data, content_type_for(ext))

    tf = TextbookFile(
        id=file_id,
        textbook_id=textbook_id,
        owner_student_id=owner_id,
        filename=filename,
        file_type=ext,
        storage_path=storage_path,
        file_size=len(data),
    )
    db.add(tf)
    await db.commit()

    return {
        "file_id": file_id,
        "filename": filename,
        "file_type": ext,
        "file_size": len(data),
        "storage_path": storage_path,
    }


# ── 文件列表 ─────────────────────────────────────────────────────────

@app.get("/v1/textbook-files")
async def list_textbook_files(
    textbook_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/textbook-files?textbook_id=xxx
    返回：某教材的平台预置文件 + 当前学生自传的文件。
    """
    if textbook_id:
        # 传 textbook_id：该教材的平台预置文件 + 学生在该教材下自传的文件
        stmt = select(TextbookFile).where(
            or_(
                (TextbookFile.textbook_id == textbook_id) & (TextbookFile.owner_student_id == None),  # noqa: E711
                (TextbookFile.textbook_id == textbook_id) & (TextbookFile.owner_student_id == current_user.id),
            )
        ).order_by(TextbookFile.uploaded_at.desc())
    else:
        # 不传 textbook_id：当前学生自传的所有文件（含无 textbook_id 的）
        stmt = select(TextbookFile).where(
            TextbookFile.owner_student_id == current_user.id
        ).order_by(TextbookFile.uploaded_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "file_id": r.id,
            "textbook_id": r.textbook_id,
            "owner_student_id": str(r.owner_student_id) if r.owner_student_id else None,
            "filename": r.filename,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "uploaded_at": r.uploaded_at.isoformat(),
        }
        for r in rows
    ]


# ── 文件内容下载 ──────────────────────────────────────────────────────

@app.get("/v1/textbook-files/{file_id}/content")
async def get_textbook_file_content(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/textbook-files/{file_id}/content — 下载文件 blob。
    - 平台预置（owner_student_id IS NULL）：所有认证用户可读
    - 自传文件：仅 owner 可读
    """
    tf = (await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 权限校验
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    try:
        data = await asyncio.to_thread(download_file, tf.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="存储对象不存在")

    ct = content_type_for(tf.file_type)
    return Response(content=data, media_type=ct, headers={
        "Content-Disposition": f'attachment; filename="{tf.filename}"',
    })


# ── 高亮 CRUD ────────────────────────────────────────────────────────

class HighlightCreate(BaseModel):
    file_id: str
    color: str = "yellow"
    text: str
    note: Optional[str] = None
    location_json: dict = {}


class HighlightPatch(BaseModel):
    color: Optional[str] = None
    note: Optional[str] = None


@app.post("/v1/highlights", status_code=201)
async def create_highlight(
    body: HighlightCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tf = (await db.execute(select(TextbookFile).where(TextbookFile.id == body.file_id))).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 仅 owner 或平台预置文件可高亮
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    if body.color not in ("yellow", "green", "blue", "red"):
        raise HTTPException(status_code=400, detail="color 必须是 yellow/green/blue/red 之一")

    hl = Highlight(
        id=_new_str_id(),
        student_id=current_user.id,
        file_id=body.file_id,
        color=body.color,
        highlighted_text=body.text,
        note=body.note,
        location_json=body.location_json,
    )
    db.add(hl)
    await db.commit()
    await db.refresh(hl)
    return _hl_dict(hl)


@app.get("/v1/highlights")
async def list_highlights(
    file_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Highlight).where(Highlight.student_id == current_user.id)
    if file_id:
        stmt = stmt.where(Highlight.file_id == file_id)
    stmt = stmt.order_by(Highlight.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_hl_dict(r) for r in rows]


@app.patch("/v1/highlights/{highlight_id}")
async def patch_highlight(
    highlight_id: str,
    body: HighlightPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hl = (await db.execute(
        select(Highlight).where(Highlight.id == highlight_id, Highlight.student_id == current_user.id)
    )).scalar_one_or_none()
    if not hl:
        raise HTTPException(status_code=404, detail="高亮不存在")

    if body.color is not None:
        hl.color = body.color
    if body.note is not None:
        hl.note = body.note
    hl.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(hl)
    return _hl_dict(hl)


@app.delete("/v1/highlights/{highlight_id}", status_code=204)
async def delete_highlight(
    highlight_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hl = (await db.execute(
        select(Highlight).where(Highlight.id == highlight_id, Highlight.student_id == current_user.id)
    )).scalar_one_or_none()
    if not hl:
        raise HTTPException(status_code=404, detail="高亮不存在")
    # 解除 reading_notes 的外键引用，再删除
    await db.execute(
        update(ReadingNote).where(ReadingNote.highlight_id == highlight_id).values(highlight_id=None)
    )
    await db.delete(hl)
    await db.commit()


def _hl_dict(hl: Highlight) -> dict:
    return {
        "id": hl.id,
        "file_id": hl.file_id,
        "student_id": str(hl.student_id),
        "color": hl.color,
        "text": hl.highlighted_text,
        "note": hl.note,
        "location_json": hl.location_json,
        "created_at": hl.created_at.isoformat(),
        "updated_at": hl.updated_at.isoformat(),
    }


# ── 独立笔记 CRUD ────────────────────────────────────────────────────

class ReadingNoteCreate(BaseModel):
    file_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    highlight_id: Optional[str] = None


class ReadingNotePatch(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


@app.post("/v1/reading-notes", status_code=201)
async def create_reading_note(
    body: ReadingNoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.highlight_id:
        hl = (await db.execute(
            select(Highlight).where(Highlight.id == body.highlight_id, Highlight.student_id == current_user.id)
        )).scalar_one_or_none()
        if not hl:
            raise HTTPException(status_code=404, detail="高亮不存在")

    rn = ReadingNote(
        id=_new_str_id(),
        student_id=current_user.id,
        file_id=body.file_id,
        title=body.title,
        content=body.content,
        highlight_id=body.highlight_id,
    )
    db.add(rn)
    await db.commit()
    await db.refresh(rn)
    return _rn_dict(rn)


@app.get("/v1/reading-notes")
async def list_reading_notes(
    file_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ReadingNote)
        .where(ReadingNote.student_id == current_user.id, ReadingNote.deleted_at == None)  # noqa: E711
    )
    if file_id:
        stmt = stmt.where(ReadingNote.file_id == file_id)
    stmt = stmt.order_by(ReadingNote.updated_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_rn_dict(r) for r in rows]


@app.patch("/v1/reading-notes/{note_id}")
async def patch_reading_note(
    note_id: str,
    body: ReadingNotePatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rn = (await db.execute(
        select(ReadingNote).where(
            ReadingNote.id == note_id,
            ReadingNote.student_id == current_user.id,
            ReadingNote.deleted_at == None,  # noqa: E711
        )
    )).scalar_one_or_none()
    if not rn:
        raise HTTPException(status_code=404, detail="笔记不存在")

    if body.title is not None:
        rn.title = body.title
    if body.content is not None:
        rn.content = body.content
    rn.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rn)
    return _rn_dict(rn)


@app.delete("/v1/reading-notes/{note_id}", status_code=204)
async def delete_reading_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rn = (await db.execute(
        select(ReadingNote).where(
            ReadingNote.id == note_id,
            ReadingNote.student_id == current_user.id,
            ReadingNote.deleted_at == None,  # noqa: E711
        )
    )).scalar_one_or_none()
    if not rn:
        raise HTTPException(status_code=404, detail="笔记不存在")
    rn.deleted_at = datetime.now(timezone.utc)
    await db.commit()


def _rn_dict(rn: ReadingNote) -> dict:
    return {
        "id": rn.id,
        "student_id": str(rn.student_id),
        "file_id": rn.file_id,
        "title": rn.title,
        "content": rn.content,
        "highlight_id": rn.highlight_id,
        "created_at": rn.created_at.isoformat(),
        "updated_at": rn.updated_at.isoformat(),
    }

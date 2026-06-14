from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from uuid import UUID
import uuid
from typing import Optional, List
from datetime import datetime, date, timezone
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import os
import json

from obase.db import get_db, SessionLocal
from services.logging_config import configure_logging, logger
from obase.prior_provider import PriorProvider
from obase.llm import register_default_providers
from obase.auth import decode_access_token
from omodul.cognitive import InteractionInput
from omodul.auth import (
    send_code_workflow,
    register_student_workflow,
    login_workflow,
    AuthConfig,
    SendCodeInput,
    RegisterStudentInput,
    LoginInput
)
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
    InteractionEvent, KCMastery, MasterySnapshot, Paper, PaperStatus,
    ParentStudent, SocraticSession, User, UserRole, WrongQuestion,
)
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
    async with SessionLocal() as session:
        await seed_bkt_priors(session)
        await session.commit()
        await PriorProvider.warm_up(session)
    register_default_providers()
    yield

app = FastAPI(title="Mneme API", version="0.1.0", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "healthy", "service": "mneme-api"}

# ===== §8 认证 API =====

@app.post("/v1/auth/send-code")
async def post_send_code(
    payload: SendCodeInput
):
    """
    POST /v1/auth/send-code
    发送短信验证码（dev mock）。
    """
    config = AuthConfig()
    result = await send_code_workflow(config, payload)
    return result["findings"]

@app.post("/v1/auth/register/student")
async def post_register_student(
    payload: RegisterStudentInput,
    db: AsyncSession = Depends(get_db)
):
    """注册学生并返回 Token。"""
    config = AuthConfig()
    result = await register_student_workflow(config, payload, db)
    if result["status"] == "failed":
        status_code = 400
        if result["findings"] and isinstance(result["findings"], dict):
            status_code = result["findings"].get("error_code", 400)
        raise HTTPException(status_code=status_code, detail=result["error"])
    await db.commit()
    return result["findings"]

@app.post("/v1/auth/login")
async def post_login(
    payload: LoginInput,
    db: AsyncSession = Depends(get_db)
):
    """登录并返回 Token。"""
    config = AuthConfig()
    result = await login_workflow(config, payload, db)
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    return result["findings"]

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
    # Placeholder — real impl would call generate_lesson_page omodul
    return {"question_id": str(question_id), "plot_data": None,
            "question_text": wq.question_text, "self_check_passed": None, "cached": False}


# ===== §I.1 变式题 =====

@app.post("/v1/practice/generate")
async def post_practice_generate(
    kc_id: str = Query(...),
    count: int = Query(3),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/generate — 生成变式题（调 oskill.generate_practice_set）。"""
    from oskill.generate_practice_set import PracticeSetConfig, generate_practice_set
    from oskill.interleave_select import QuestionItem
    kc = get_kc(kc_id)
    if not kc:
        raise HTTPException(status_code=404, detail="KC not found")
    # Build a minimal question bank from KC data
    wqs = (await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.knowledge_points.has_key(kc_id)  # type: ignore[attr-defined]
        ).limit(20)
    )).scalars().all()
    bank = [
        QuestionItem(question_id=str(w.id), kc_id=kc_id, difficulty=0.5)
        for w in wqs
    ]
    # Fallback: create placeholder items if no wrong questions
    if not bank:
        bank = [QuestionItem(question_id=f"{kc_id}-placeholder-{i}", kc_id=kc_id, difficulty=0.5)
                for i in range(count)]
    cfg = PracticeSetConfig(target_count=count)
    try:
        result = generate_practice_set(bank, config=cfg)
        items = result.questions
    except ValueError:
        # Interleave requires ≥2 KC IDs; return filtered bank directly
        items = bank[:count]
    return {
        "kc_id": kc_id,
        "kc_name": kc.get("name", kc_id),
        "items": [{"question_id": q.question_id, "kc_id": q.kc_id, "difficulty": q.difficulty}
                  for q in items],
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

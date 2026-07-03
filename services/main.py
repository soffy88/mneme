from obase.provider_registry import ProviderRegistry
from pydantic import BaseModel, Field
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
    Response,
    Request,
    Body,
)
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update, or_, text
from uuid import UUID
import uuid
from typing import Optional
from datetime import datetime, date, timezone, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import shutil
import os
import json
import re

from obase.db import get_db, SessionLocal
from services.logging_config import configure_logging, logger
from obase.prior_provider import PriorProvider
from obase.auth import decode_access_token
from omodul.cognitive import InteractionInput
from oprim.prereq_graph import topo_sort_by_prereq, fringe_status
from services.learner_model import MASTERED as _MASTERED
from oprim.calibration import brier_calibration
from omodul.auth import SendCodeInput, RegisterStudentInput, LoginInput
import services.auth_service as auth_service
from services.sms import get_sms_provider
from omodul.paper import upload_paper_workflow, PaperConfig, PaperUploadInput
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
    DailyMission,
    EffortfulGain,
    EvaluationRun,
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    Paper,
    ParentStudent,
    SocraticSession,
    User,
    UserRole,
    WrongQuestion,
    TextbookFile,
    Highlight,
    ReadingNote,
    Textbook,
    KnowledgeCluster,
    KnowledgeUnit,
)
from services.storage import upload_file, download_file, content_type_for
from data.guangdong_math_kc import KC_LIST, get_kc

# ===== §8 认证依赖 =====
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/auth/login", auto_error=False)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    stmt = select(User).where(User.id == uuid.UUID(user_id), User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_student_access(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """越权防护：仅学生本人或其绑定家长可访问该学生数据（合规红线，含未成年人）。
    student_id 从路径自动解析。"""
    if current_user.id == student_id:
        return current_user
    link = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="无权访问该学生数据")
    return current_user


async def _ensure_student_access(
    db: AsyncSession, current_user: User, student_id: Optional[UUID]
) -> None:
    """IDOR 防护（student_id 在 body/query/关联行里的场景）：
    仅学生本人或其绑定家长，否则 403。与 require_student_access 同规则。"""
    if student_id is None or current_user.id == student_id:
        return
    link = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="无权访问该学生数据")


def _ensure_student_self(current_user: User, student_id: Optional[UUID]) -> None:
    """学习数据写操作（答题/会话/任务完成）仅学生本人可执行；
    家长只读，不可替孩子写认知数据（否则污染 BKT/FSRS 档案）。"""
    if student_id is not None and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="仅学生本人可执行该操作")


async def _ensure_session_owner(
    db: AsyncSession, current_user: User, session_id: UUID
) -> SocraticSession:
    """会话续写鉴权：苏格拉底/物理受力/阅读引导共用 SocraticSession，
    仅会话归属学生本人可继续（防会话劫持）。"""
    session = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.student_id is not None and session.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session


def _assert_prod_safety() -> None:
    """生产环境(MNEME_ENV=prod)安全闸门：默认 JWT 密钥 / mock 万能码 一律拒启动。
    demo/dev 环境放行（mock 是无短信通道时的演示机制）。"""
    import os as _os
    from obase.config import settings as _s

    if _os.environ.get("MNEME_ENV", "dev").lower() != "prod":
        return
    problems = []
    if _s.JWT_SECRET == "mneme-dev-secret-change-in-prod!":
        problems.append("JWT_SECRET 仍是默认开发密钥（可伪造任意 token）")
    if _os.environ.get("SMS_PROVIDER", "mock").lower() != "aliyun":
        problems.append("SMS_PROVIDER 非 aliyun（123456 万能码可登录任何人）")
    if problems:
        raise RuntimeError("❌ 生产环境安全校验失败，拒绝启动：" + "；".join(problems))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _assert_prod_safety()

    # 3O 内核契约自检：内核仓静默回退（丢字段）会让去抖/个性化/苏格拉底续接等
    # 悄悄失效而不报错，这里启动期显式告警，便于第一时间发现。
    from services.kernel_selfcheck import check_kernel_contract

    _missing = check_kernel_contract()
    if _missing:
        logger.error(
            "⚠️ 3O 内核契约缺失（功能可能静默失效，检查内核仓分支是否为 feat/edu-audit-fixes）: %s",
            ", ".join(_missing),
        )

    # Initialize obase infrastructure tables
    from obase.config import settings
    from obase.persistence.pool import PgPool
    from obase.error_tag_store import ensure_error_tag_table
    from obase.interaction_history import ensure_interaction_history_table

    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = await PgPool.get_or_create(dsn=dsn)
    await ensure_error_tag_table(pool)
    await ensure_interaction_history_table(pool)

    async with SessionLocal() as session:
        await seed_bkt_priors(session)
        await session.commit()
        await PriorProvider.warm_up(session)
    # LLM/VLM provider 装配（单源，API 与 worker 共用；含 MNEME_LLM=ollama 覆盖）
    from services.providers.setup import configure_llm_providers

    _llm_tag = configure_llm_providers()
    logger.info(f"LLM default provider: {_llm_tag}")

    # Register English speaking practice generic callers (real or mock)
    from services.providers.aliyun_pronunciation import AliyunPronunciationCaller

    aliyun_key = settings.ALIYUN_ACCESS_KEY_ID
    aliyun_secret = settings.ALIYUN_ACCESS_KEY_SECRET
    if aliyun_key and aliyun_secret:
        ProviderRegistry.register(
            "pronunciation",
            "aliyun",
            AliyunPronunciationCaller(
                aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY
            ),
        )
        ProviderRegistry.register(
            "pronunciation",
            "default",
            AliyunPronunciationCaller(
                aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY
            ),
        )
    else:
        logger.warning("阿里云语音评测未配置，口语陪练功能将使用 mock 评分")

        class MockPronunciationCaller:
            async def __call__(self, *, audio_b64: str, reference_text: str, **kwargs):
                from oprim._mneme_speech_types import PronunciationResult

                return PronunciationResult(
                    overall_score=0.85,
                    fluency_score=0.80,
                    accuracy_score=0.90,
                    word_scores=[],
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
    allow_origins=[
        "https://mneme.uex.hk",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== §8 认证 API =====


@app.post("/v1/auth/send-code")
async def post_send_code(payload: SendCodeInput):
    """POST /v1/auth/send-code — 发送短信验证码，存 Redis TTL=5min，60s防刷。"""
    import services.main as _self

    result = await auth_service.send_code(payload.phone, _self._sms_provider)
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["message"])
    return result


def _require_registration_open() -> None:
    """公网注册闸门（默认关）。SMS 仍是 mock（万能码 123456）时公网放开注册 = 任何人
    可注册（含 <14 岁绕过）。阿里云短信报备 + 关 mock 码前，用 REGISTRATION_OPEN=1 才开。"""
    import os as _os

    if _os.environ.get("REGISTRATION_OPEN", "0").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            status_code=403,
            detail="注册暂未开放（公网注册需短信实名，报备后开启）",
        )


@app.post("/v1/auth/register/student", status_code=201)
async def post_register_student(
    payload: RegisterStudentInput,
    db: AsyncSession = Depends(get_db),
):
    """注册学生：Redis验证码校验 + 合规校验 + 写库 + 返回JWT。"""
    _require_registration_open()
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


class RegisterParentInput(BaseModel):
    phone: str
    code: str
    name: str
    invite_code: str


@app.post("/v1/auth/register/parent", status_code=201)
async def post_register_parent(
    payload: RegisterParentInput,
    db: AsyncSession = Depends(get_db),
):
    """注册家长：验证码校验 + 手机唯一 + 凭 invite_code 绑定孩子 + 返回JWT。"""
    _require_registration_open()
    result = await auth_service.register_parent(
        db=db,
        phone=payload.phone,
        code=payload.code,
        name=payload.name,
        invite_code=payload.invite_code,
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
async def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息。"""
    return {
        "id": str(user.id),
        "phone": user.phone,
        "role": user.role.value,
        "name": user.name,
        "grade": getattr(user, "grade", None),
        # 学生的邀请码：前端展示给学生，家长凭此注册/绑定（家长账号为 None）
        "invite_code": user.invite_code,
    }


# ===== §8 认知状态 API =====


@app.post("/v1/interaction")
async def post_interaction(
    interaction: InteractionInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/interaction — 处理一次答题交互并更新认知状态。仅学生本人可写。"""
    _ensure_student_self(current_user, interaction.student_id)
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
            difficulty=interaction.difficulty,
            predicted_confidence=interaction.predicted_confidence,
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
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/mastery/curve/{student_id}/{kc_id} — mastery_snapshots 月度时间序列。"""
    rows = (
        (
            await db.execute(
                select(MasterySnapshot)
                .where(MasterySnapshot.student_id == student_id)
                .where(MasterySnapshot.knowledge_point == kc_id)
                .order_by(MasterySnapshot.snapshot_month)
            )
        )
        .scalars()
        .all()
    )
    kc = await db.get(KnowledgeUnit, kc_id)
    _kcd = get_kc(kc_id)
    return {
        "kc_id": kc_id,
        "kc_name": (kc.name if kc else ((_kcd.get("name") if _kcd else None) or kc_id)),
        "points": [
            {
                "month": r.snapshot_month.isoformat(),
                "mastery": round(r.long_term_mastery, 4) if r.long_term_mastery else 0,
                "dominant_error_type": r.dominant_error_type,
            }
            for r in rows
        ],
    }


@app.get("/v1/mastery/{student_id}")
async def get_mastery(
    student_id: UUID,
    now: Optional[datetime] = None,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/mastery/{student_id} — 掌握度总览（按薄弱排序，含百分位）。"""
    try:
        items = await mastery_overview(db, student_id, now=now)
        # 补 KU 友好名称（命名已统一），避免前端标题空白/显示原始 id
        if isinstance(items, list) and items:
            ids = list({it.get("kc_id") for it in items if it.get("kc_id")})
            if ids:
                krows = (
                    await db.execute(
                        select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                            KnowledgeUnit.id.in_(ids)
                        )
                    )
                ).all()
                nm = {kid: name for kid, name in krows}
                for it in items:
                    kid = it.get("kc_id")
                    name = nm.get(kid)
                    if not name:  # 回退广东 KC 字典(GDMATH-* 等老命名)
                        kc = get_kc(kid)
                        name = (kc.get("name") if kc else None) or kid
                    it["kc_name"] = name
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/review-queue/{student_id}")
async def get_review_queue(
    student_id: UUID,
    now: Optional[datetime] = None,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
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


async def _textbook_file_map(
    db: AsyncSession, textbook_ids: list[str]
) -> dict[str, str]:
    """返回 {textbook_id: file_id}，取每个教材的第一个平台预置 PDF。"""
    if not textbook_ids:
        return {}
    rows = (
        await db.execute(
            select(TextbookFile.textbook_id, TextbookFile.id)
            .where(
                TextbookFile.textbook_id.in_(textbook_ids),
                TextbookFile.owner_student_id.is_(None),
                TextbookFile.file_type == "pdf",
            )
            .order_by(TextbookFile.uploaded_at)
        )
    ).all()
    # 每个 textbook_id 只取第一条
    result: dict[str, str] = {}
    for tid, fid in rows:
        if tid not in result:
            result[tid] = fid
    return result


async def _mastery_map(
    db: AsyncSession, student_id: UUID, ku_ids: list[str]
) -> dict[str, float]:
    """返回 {ku_id: p_mastery}，只查询该学生。"""
    if not ku_ids or not student_id:
        return {}
    rows = (
        await db.execute(
            select(KCMastery.knowledge_point, KCMastery.p_mastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point.in_(ku_ids),
            )
        )
    ).all()
    return {kp: (pm or 0.0) for kp, pm in rows}


def _mastery_color(p: float | None) -> str:
    # L1 单源：委托 learner_model.mastery_color（阈值统一在那里）
    from services.learner_model import mastery_color

    return mastery_color(p)


_FREQ_RANK = {"high": 2, "mid": 1, "low": 0}
_MASTERY_RANK = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}


# 拓扑排序已上移至 oprim.prereq_graph.topo_sort_by_prereq（确定性算法归 oprim）


@app.get("/v1/knowledge-points")
async def list_knowledge_points(
    subject: Optional[str] = Query(None),
    textbook_id: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    student_id: Optional[UUID] = Query(None),
    sort: str = Query("chapter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/knowledge-points
    查询知识单元，支持按 subject / textbook_id / cluster_id 筛选。
    可选 student_id → 附带该生掌握度（p_mastery / mastery_color）。
    sort: chapter(默认)|topic|mastery|difficulty|exam_freq|prereq
    返回带 cluster 信息、textbook_file_id 和 AII 字段的 KU 列表。
    """
    await _ensure_student_access(db, current_user, student_id)
    stmt = (
        select(KnowledgeUnit, KnowledgeCluster, Textbook)
        .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
        .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
    )
    if subject:
        stmt = stmt.where(Textbook.subject == subject)
    if textbook_id:
        stmt = stmt.where(KnowledgeUnit.textbook_id == textbook_id)
    if cluster_id:
        stmt = stmt.where(KnowledgeUnit.cluster_id == cluster_id)
    stmt = stmt.order_by(KnowledgeCluster.display_order, KnowledgeUnit.id)

    rows = (await db.execute(stmt)).all()

    # 批量查 textbook_file_id 和学生掌握度（各1次查询）
    all_tb_ids = list({tb.id for _, _, tb in rows})
    all_ku_ids = [ku.id for ku, _, _ in rows]
    file_map = await _textbook_file_map(db, all_tb_ids)
    mastery_map = await _mastery_map(db, student_id, all_ku_ids) if student_id else {}

    items = [
        {
            "id": ku.id,
            "name": ku.name,
            "description": ku.description,
            "textbook_id": ku.textbook_id,
            "textbook_file_id": file_map.get(ku.textbook_id),
            "cluster_id": ku.cluster_id,
            "cluster_name": kc.name,
            "cluster_order": kc.display_order,
            "subject": tb.subject,
            "grade": tb.grade,
            "edition": tb.edition,
            "book_name": tb.book_name,
            "prerequisites": ku.prerequisites,
            "related_kus": ku.related_kus,
            "difficulty": round(ku.difficulty, 4),
            "exam_frequency": ku.exam_frequency,
            "question_types": ku.question_types,
            "ku_type": ku.ku_type,
            "curriculum_standard": ku.curriculum_standard,
            "mastery_levels": ku.mastery_levels,
            "verified": ku.verified,
            "p_mastery": mastery_map.get(ku.id),
            "mastery_color": _mastery_color(mastery_map.get(ku.id)),
            # KST fringe（掌握门控）：mastered/learning/learnable/locked；仅在有 student 时有意义
            "fringe": (
                fringe_status(mastery_map.get(ku.id), ku.prerequisites, mastery_map)
                if student_id
                else None
            ),
        }
        for ku, kc, tb in rows
    ]

    if sort == "textbook":
        items.sort(
            key=lambda x: (
                _grade_sort_key(x["grade"]),
                x["textbook_id"].lower(),
                x["id"],
            )
        )
    elif sort == "topic":
        items.sort(key=lambda x: (x["cluster_name"], x["id"]))
    elif sort == "mastery":
        items.sort(
            key=lambda x: (
                _MASTERY_RANK.get(x["mastery_color"], 2),
                -(x["p_mastery"] or 0),
            )
        )
    elif sort == "difficulty":
        items.sort(key=lambda x: x["difficulty"])
    elif sort == "exam_freq":
        items.sort(key=lambda x: -_FREQ_RANK.get(x["exam_frequency"], 1))
    elif sort == "prereq":
        items = topo_sort_by_prereq(items)

    # verified 优先（稳定排序，保留各 sort 模式内的相对顺序）；
    # prereq 拓扑序是硬约束，不参与重排
    if sort != "prereq":
        items.sort(key=lambda x: not x["verified"])

    return items


@app.get("/v1/knowledge-points/{ku_id}")
async def get_knowledge_point(
    ku_id: str,
    student_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/knowledge-points/{ku_id} — 单个 KU 详情（含掌握度和前置KU掌握度）。"""
    await _ensure_student_access(db, current_user, student_id)
    row = (
        await db.execute(
            select(KnowledgeUnit, KnowledgeCluster, Textbook)
            .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
            .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
            .where(KnowledgeUnit.id == ku_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    ku, kc, tb = row

    file_map = await _textbook_file_map(db, [ku.textbook_id])
    # 掌握度：当前 KU + 所有前置 KU
    prereq_ids = list(ku.prerequisites) if ku.prerequisites else []
    all_ids = [ku_id] + prereq_ids
    mastery_map = await _mastery_map(db, student_id, all_ids) if student_id else {}

    prereq_mastery = [
        {
            "ku_id": pid,
            "p_mastery": mastery_map.get(pid),
            "mastery_color": _mastery_color(mastery_map.get(pid)),
        }
        for pid in prereq_ids
    ]

    return {
        "id": ku.id,
        "name": ku.name,
        "description": ku.description,
        "textbook_id": ku.textbook_id,
        "textbook_file_id": file_map.get(ku.textbook_id),
        "cluster_id": ku.cluster_id,
        "cluster_name": kc.name,
        "subject": tb.subject,
        "grade": tb.grade,
        "prerequisites": ku.prerequisites,
        "related_kus": ku.related_kus,
        "difficulty": round(ku.difficulty, 4),
        "exam_frequency": ku.exam_frequency,
        "question_types": ku.question_types,
        "ku_type": ku.ku_type,
        "curriculum_standard": ku.curriculum_standard,
        "mastery_levels": ku.mastery_levels,
        "p_mastery": mastery_map.get(ku_id),
        "mastery_color": _mastery_color(mastery_map.get(ku_id)),
        "prereq_mastery": prereq_mastery,
        "rich_content": ku.rich_content,
    }


# ===== §3 试卷接口 =====


@app.post("/v1/papers/upload")
async def post_paper_upload(
    student_id: UUID = Query(...),
    file: UploadFile = File(...),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /v1/papers/upload
    上传一张试卷并启动处理流程。鉴权：学生本人或绑定家长。
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
            filename=file.filename or "unknown.jpg",
        )

        result = await upload_paper_workflow(config, payload, db)

        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result["error"])

        # 触发异步分析（OCR→批改→共同断点→认知更新）。
        # 冷启动钩子核心：上传后试卷由 Celery 真正分析，前端轮询 GET /v1/papers/{id} 状态。
        findings = result["findings"]
        try:
            from tasks.paper_tasks import process_paper

            process_paper.delay(findings["paper_id"])
        except Exception as exc:  # noqa: BLE001 — broker 不可用不应阻断上传
            logger.error(
                f"dispatch process_paper failed for {findings.get('paper_id')}: {exc}"
            )

        return findings

    finally:
        # 清理临时文件
        if local_path.exists():
            os.remove(local_path)


@app.get("/v1/papers/{paper_id}")
async def get_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/papers/{id} — 试卷详情 + 错题 + 共同断点。鉴权：卷主本人或绑定家长。"""
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    await _ensure_student_access(db, current_user, paper.student_id)
    wqs = (
        (
            await db.execute(
                select(WrongQuestion).where(WrongQuestion.paper_id == paper_id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "paper": {
            "id": str(paper.id),
            "student_id": str(paper.student_id),
            "status": paper.status.value if paper.status else None,
            "subject": paper.subject,
            "created_at": paper.created_at.isoformat() if paper.created_at else None,
        },
        "wrong_questions": [
            {
                "id": str(w.id),
                "kc_ids": list((w.knowledge_points or {}).keys()),
                "error_type": w.error_type.value if w.error_type else None,
            }
            for w in wqs
        ],
    }


@app.get("/v1/papers")
async def list_papers(
    student_id: UUID = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/papers — 试卷列表。鉴权：学生本人或绑定家长。"""
    stmt = (
        select(Paper)
        .where(Paper.student_id == student_id)
        .order_by(Paper.created_at.desc())
    )
    papers = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(p.id),
            "status": p.status.value if p.status else None,
            "subject": p.subject,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in papers
    ]


# ===== §C.2 多孩子绑定 =====


@app.post("/v1/auth/bind-child")
async def post_bind_child(
    invite_code: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/auth/bind-child — 家长绑定孩子。"""
    student = (
        await db.execute(
            select(User).where(
                User.invite_code == invite_code, User.role == UserRole.student
            )
        )
    ).scalar_one_or_none()
    if not student:
        raise HTTPException(
            status_code=404, detail="Student not found with invite code"
        )
    existing = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == current_user.id,
                ParentStudent.student_id == student.id,
            )
        )
    ).scalar_one_or_none()
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
    rows = (
        await db.execute(
            select(ParentStudent, User)
            .join(User, ParentStudent.student_id == User.id)
            .where(ParentStudent.parent_id == current_user.id)
            .order_by(ParentStudent.display_order)
        )
    ).all()
    return [
        {"student_id": str(ps.student_id), "name": u.name, "grade": u.grade}
        for ps, u in rows
    ]


# ===== §E.1 今日目标 =====


@app.get("/v1/missions/today/{student_id}")
async def get_today_mission(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/missions/today/{student_id} — 获取或创建今日目标。"""
    try:
        result = await get_or_create_mission(db, student_id)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/missions/{mission_id}/complete")
async def post_complete_mission(
    mission_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/missions/{id}/complete — 完成任务，更新 streak。仅任务归属学生本人。"""
    mission = await db.get(DailyMission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    _ensure_student_self(current_user, mission.student_id)
    result = await complete_mission(db, mission_id)
    await db.commit()
    return result


# ===== §E.2 每日学科计划（桩接口） =====


@app.get("/v1/daily-plan/{student_id}")
async def get_daily_plan(
    student_id: UUID,
    subject: Optional[str] = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/daily-plan/{student_id}?subject=xxx — 每日学习计划规则引擎。
    鉴权：学生本人或绑定家长（原先只验登录不验归属）。

    subject 不传 → 所有科目汇总（首页用）
    subject=math  → 单科详细（学科页用）

    优先级：P1 FSRS到期 > P2 错题 > P3 薄弱 > P4 新知识点
    """
    from services.daily_plan_service import build_daily_plan

    return await build_daily_plan(db, student_id, subject=subject)


# ===== §F.0 努力收益看板（M-F）=====


@app.get("/v1/effortful-gains/{student_id}")
async def get_effortful_gains(
    student_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/effortful-gains/{student_id} — 努力收益看板（M-F）。
    展示"做得吃力、但记忆稳定性提升最多"的题，按 effortful_gain 降序。
    """
    rows = (
        (
            await db.execute(
                select(EffortfulGain)
                .where(EffortfulGain.student_id == student_id)
                .order_by(EffortfulGain.effortful_gain.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    qids = [r.question_id for r in rows if r.question_id]
    kc_map: dict = {}
    if qids:
        wqs = (
            await db.execute(
                select(WrongQuestion.id, WrongQuestion.knowledge_points).where(
                    WrongQuestion.id.in_(qids)
                )
            )
        ).all()
        for qid, kps in wqs:
            kc_map[qid] = next(iter((kps or {}).values()), None)

    return {
        "top_gains": [
            {
                "question_id": str(r.question_id) if r.question_id else None,
                "kc": kc_map.get(r.question_id),
                "struggle_score": r.struggle_score,
                "retention_delta": r.retention_delta,
                "effortful_gain": r.effortful_gain,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ]
    }


@app.get("/v1/weak-roots/{student_id}")
async def get_weak_roots(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/weak-roots/{student_id} — 前置图谱归因。
    对薄弱知识点上溯前置链，找出"先补根再补叶"的薄弱/未练前置。
    """
    from services.cognitive_service import weakness_roots

    return {"roots": await weakness_roots(db, student_id)}


@app.get("/v1/weekly-digest/{student_id}")
async def get_weekly_digest(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/weekly-digest/{student_id} — 留存引擎：连续天数 + 本周成长摘要。"""
    from services.cognitive_service import weekly_digest

    return await weekly_digest(db, student_id)


@app.get("/v1/parent/report/{student_id}")
async def get_parent_report(
    student_id: UUID,
    date: Optional[date] = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/report/{student_id}?date — 家长学习日报（可转发微信）。"""
    from services.cognitive_service import daily_report

    return await daily_report(db, student_id, date)


@app.get("/v1/calibration/{student_id}")
async def get_calibration(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/calibration/{student_id} — JOL 校准（判断学习的准度）。
    比较作答前自评把握(predicted_confidence)与实际对错：
    brier 越低越准；overconfidence>0=高估自己(努力错觉)，<0=低估自己。
    """
    rows = (
        await db.execute(
            select(InteractionEvent.predicted_confidence, InteractionEvent.is_correct)
            .where(InteractionEvent.student_id == student_id)
            .where(InteractionEvent.predicted_confidence.is_not(None))
        )
    ).all()
    return brier_calibration(
        predicted=[float(p) for p, _ in rows],
        actual=[1.0 if c else 0.0 for _, c in rows],
    )


@app.get("/v1/moat/evaluation-history")
async def get_evaluation_history(
    limit: int = Query(52, ge=1, le=520),
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/evaluation-history — 护城河实证历史（周评估 AUC/log-loss 落表）。
    登录即可读（模型质量是全体聚合数据，无个人信息）；按 ran_at 倒序。
    """
    rows = (
        (
            await db.execute(
                select(EvaluationRun).order_by(EvaluationRun.ran_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": str(r.id),
                "ran_at": r.ran_at.isoformat() if r.ran_at else None,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "n_events": r.n_events,
                "n_students": r.n_students,
                "auc": round(r.auc, 4) if r.auc is not None else None,
                "log_loss": round(r.log_loss, 4) if r.log_loss is not None else None,
                "meta": r.meta,
            }
            for r in rows
        ]
    }


@app.get("/v1/moat/retention-metrics")
async def get_retention_metrics(
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/retention-metrics — 留存三指标（T.2）。

    D7 留存 / 到期复习完成率 / 保留探针校准（实测召回 vs FSRS 预测 R）。
    登录即可读（全体聚合数据，无个人信息）；口径见 services.retention_service。
    """
    from services.retention_service import retention_metrics

    return await retention_metrics(db)


@app.get("/v1/moat/learning-metrics")
async def get_learning_metrics(
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/learning-metrics — L0 学习层北极星四指标（架构重排）。

    掌握速度 / 延迟保持率(探针升格) / 迁移率 / 校准度。**一级指标**——模型层(AUC)与
    产品层(留存)降为从属。登录可读，全体聚合无 PII。红线：留存涨而学习平 = 回滚。
    """
    from services.learning_metrics_service import compute_learning_metrics

    return await compute_learning_metrics(db)


@app.get("/v1/teaching/policy")
async def get_teaching_policy(
    student_id: UUID,
    kc_id: str,
    context: str = Query("system_taught"),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """L2 教学引擎：返回该 (学生, KU, 情境) 下的答案分级政策 + 当前学习阶段。
    情境 context: system_taught(系统同构新知) / own_homework(自带原题) / writing(写作) / stuck(卡壳)。
    前端据此决定"给完整样例"还是"苏格拉底提问"。红线：own_homework/writing 恒不给。
    教学引擎 feature-flag(TEACHING_ENGINE_ENABLED) 关闭时保守回退 never。"""
    import os as _os

    from oprim.answer_policy import answer_policy
    from services.learner_model import get_mastery, get_stage

    m = await get_mastery(db, student_id, kc_id)
    stage = get_stage(m["p"])
    enabled = _os.environ.get("TEACHING_ENGINE_ENABLED", "0").lower() in ("1", "true", "yes")
    pol = answer_policy(context, stage, enabled=enabled)
    return {"stage": stage, "engine_enabled": enabled, **pol}


class PlacementResponse(BaseModel):
    difficulty: float = Field(ge=0.0, le=1.0)
    is_correct: bool


class PlacementReq(BaseModel):
    responses: list[PlacementResponse]


@app.post("/v1/placement/estimate")
async def post_placement_estimate(
    body: PlacementReq,
    _auth: User = Depends(get_current_user),
):
    """L3 自适应定位：从一批 (难度, 对错) 响应估学生能力 θ(Rasch)+ SE + ZPD 难度带 +
    建议下一题难度。冷启动/入学定位用；θ 也可喂 learner_model.get_zpd_band。纯计算不落库。"""
    from oprim.ability import estimate_ability, next_item_difficulty
    from services.learner_model import get_zpd_band

    est = estimate_ability([(r.difficulty, r.is_correct) for r in body.responses])
    theta = est["theta"]
    return {
        **est,
        "zpd_band": get_zpd_band(None, theta=theta),
        "next_difficulty": next_item_difficulty(theta),
    }


class CatResponse(BaseModel):
    difficulty: float = Field(ge=0.0, le=1.0)
    is_correct: bool


class CatNextReq(BaseModel):
    subject: str = "math"
    responses: list[CatResponse] = Field(default_factory=list)
    served_ku_ids: list[str] = Field(default_factory=list)


@app.post("/v1/placement/next")
async def post_placement_next(
    body: CatNextReq,
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """L3 自适应定位会话(CAT,无状态)：交累积 (难度,对错) → 估 θ,SE<阈值或达上限即停,
    否则返回难度就近 θ 的下一题 KU。客户端累积 responses/served_ku_ids 逐轮调用。"""
    from services.placement_service import cat_next

    return await cat_next(
        db,
        subject=body.subject,
        responses=[r.model_dump() for r in body.responses],
        served_ku_ids=body.served_ku_ids,
    )


@app.get("/v1/misconception/{ku_id}")
async def get_misconception(
    ku_id: str,
    distractor: Optional[str] = Query(None),
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """L3 误解诊断（骨架）：答错时挂误解 ID + 重建方向，用于概念重建微课而非同类题再刷。
    优先精确干扰项映射(教研逐题填)，否则按 KU 名关键词退回候选(heuristic)。"""
    from oprim.misconception import diagnose_misconception

    row = (
        await db.execute(
            select(KnowledgeUnit.name, Textbook.subject)
            .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
            .where(KnowledgeUnit.id == ku_id)
        )
    ).first()
    if row is None:
        return {"misconception": None, "note": "KU 不存在"}
    name, subject = row
    m = diagnose_misconception(subject or "", name or "", ku_id=ku_id, distractor=distractor)
    return {"ku_id": ku_id, "misconception": m}


# ===== §F.1 苏格拉底会话 =====


@app.post("/v1/socratic/start")
async def post_socratic_start(
    question_id: UUID = Query(...),
    student_id: UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/start — 开始苏格拉底会话。仅学生本人。"""
    _ensure_student_self(current_user, student_id)
    result = await start_session(db, question_id, student_id)
    await db.commit()
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/v1/socratic/{session_id}/message")
async def post_socratic_message(
    session_id: UUID,
    student_message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/{id}/message — SSE 流式苏格拉底回复。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)

    async def event_stream():
        async for chunk in socratic_message_stream(db, session_id, student_message):
            yield chunk
        await db.commit()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/socratic/{session_id}/escape")
async def post_socratic_escape(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/{id}/escape — 请求答案大纲（非完整答案）。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)
    result = await escape_session(db, session_id)
    await db.commit()
    return result


@app.post("/v1/socratic/{session_id}/end")
async def post_socratic_end(
    session_id: UUID,
    outcome: str = Query("partial"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/{id}/end — 结束会话，写 outcome。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)
    result = await end_session(db, session_id, outcome)
    await db.commit()
    return result


# ===== §G.1 家长成长摘要 =====


@app.get("/v1/parent/overview/{student_id}")
async def get_parent_overview(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/overview/{student_id} — 学生学习摘要（家长视角）。"""
    rows = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )
    weak_kc = [r for r in rows if (r.p_mastery or 0) < 0.5]
    from services.cognitive_service import _get_streak_dict

    streak = await _get_streak_dict(db, student_id)
    recent_sessions = (
        (
            await db.execute(
                select(SocraticSession)
                .where(SocraticSession.student_id == student_id)
                .order_by(SocraticSession.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    return {
        "weak_kc_count": len(weak_kc),
        "total_kc_practiced": len(rows),
        "streak": streak,
        "recent_sessions": len(recent_sessions),
    }


# ===== §H.1 求解接口 =====


from services.ratelimit import rate_limit

# 匿名昂贵端点限流：每 IP 60s 内 30 次求解（防刷算力）
_solve_rate_limit = rate_limit(limit=30, window_seconds=60, scope="solve")


@app.post("/v1/solve")
async def post_solve(
    kc_id: str = Query(...),
    expression: str = Query(...),
    _: None = Depends(_solve_rate_limit),
):
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
async def get_lesson(
    question_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/lesson/{question_id} — 讲解页（缓存优先）。
    鉴权：题目归属学生本人或绑定家长（公共题库题 student_id 为空则放行）。"""
    from services.models import LessonPage

    wq = (
        await db.execute(select(WrongQuestion).where(WrongQuestion.id == question_id))
    ).scalar_one_or_none()
    if wq is not None:
        await _ensure_student_access(db, current_user, wq.student_id)

    # Cache check
    cached = (
        await db.execute(
            select(LessonPage).where(LessonPage.question_id == question_id)
        )
    ).scalar_one_or_none()
    if cached:
        return {
            "question_id": str(question_id),
            "plot_data": cached.plot_data,
            "self_check_passed": cached.self_check_passed,
            "cached": True,
        }
    if not wq:
        raise HTTPException(status_code=404, detail="Question not found")
    from omodul.generate_lesson_page import (
        LessonPageConfig,
        LessonPageInput,
        generate_lesson_page,
    )
    import hashlib as _hashlib

    kc_id = (
        next(iter(wq.knowledge_points.keys()), "")
        if isinstance(wq.knowledge_points, dict)
        else ""
    )
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
            await (
                db.commit()
            )  # 原仅 flush 无 commit → 会话关闭即回滚，lesson_pages 永远为 0
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


@app.get("/v1/question-bank")
async def list_question_bank(
    subject: Optional[str] = Query(None),
    needs_image: Optional[bool] = Query(None),
    ku_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/question-bank — 公共题库查询（student_id IS NULL）。

    ?subject=math         按学科筛选
    ?needs_image=false    只返回纯文本题（专题练习用）
    ?ku_id=...            按已匹配KU筛选
    """
    stmt = select(WrongQuestion).where(WrongQuestion.student_id.is_(None))
    if subject:
        stmt = stmt.where(WrongQuestion.subject == subject)
    if needs_image is not None:
        stmt = stmt.where(WrongQuestion.needs_image == needs_image)
    if ku_id:
        stmt = stmt.where(WrongQuestion.knowledge_points.has_key(ku_id))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    rows = (
        (
            await db.execute(
                stmt.order_by(WrongQuestion.created_at).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": str(q.id),
                "subject": q.subject,
                "question_text": q.question_text,
                "correct_answer": q.correct_answer,
                "knowledge_points": q.knowledge_points or {},
                "needs_image": q.needs_image,
                # 解析（答后展示，助学生看"为什么"）：取 gaokao analysis / ceval explanation
                "explanation": (q.profiler_analysis or {}).get("analysis")
                or (q.profiler_analysis or {}).get("explanation")
                or "",
            }
            for q in rows
        ],
    }


@app.post("/v1/practice/generate")
async def post_practice_generate(
    kc_id: str = Query(...),
    count: int = Query(3),
    difficulty: float = Query(0.5),
    question_type: str = Query("solve"),
    student_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/generate — 生成变式题（调 omodul.practice_workflow）。"""
    await _ensure_student_access(db, current_user, student_id)
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


@app.get("/v1/practice/topics")
async def list_practice_topics(
    subject: str = Query("math"),
    min_count: int = Query(5),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/practice/topics — 列出"有真实题库题（纯文本+带答案）"的练习主题及题量。

    供练习选题页用：知识体系是 GDMATH-* 命名，而题库题映射到 cmm-math-g{年级}-{主题} 键，
    这里直接列出有内容的 KU，避免学生点开练习是空的。
    """
    rows = (
        await db.execute(
            text(
                """
            select kv.key as ku_id, count(*) as n,
                   coalesce(max(ku.name), max(kv.value)) as ku_name
            from wrong_questions, jsonb_each_text(knowledge_points) as kv
            left join knowledge_units ku on ku.id = kv.key
            where student_id is null and subject = :subject and needs_image = false
              and correct_answer is not null and correct_answer <> ''
            group by kv.key having count(*) >= :min_count
            order by kv.key
            """
            ),
            {"subject": subject, "min_count": min_count},
        )
    ).all()
    return {
        "topics": [
            {"ku_id": r[0], "count": int(r[1]), "ku_name": r[2] or r[0]} for r in rows
        ]
    }


@app.get("/v1/achievements/{student_id}")
async def get_achievements(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """学生成就/徽章（从真实数据算）——驱动"愿意用"的动机钩子。多档位，含下一档进度。"""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(InteractionEvent.occurred_at).where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at >= now - timedelta(days=120),
            )
        )
    ).all()
    active = {r[0].date() for r in rows}
    cur, streak = (
        (now.date() if now.date() in active else now.date() - timedelta(days=1)),
        0,
    )
    while cur in active:
        streak += 1
        cur -= timedelta(days=1)
    total_correct = (
        await db.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.is_correct.is_(True),
            )
        )
    ).scalar() or 0
    mastered = (
        await db.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.student_id == student_id, KCMastery.p_mastery >= _MASTERED)
        )
    ).scalar() or 0
    effort = (
        await db.execute(
            select(func.count())
            .select_from(EffortfulGain)
            .where(EffortfulGain.student_id == student_id)
        )
    ).scalar() or 0

    defs = [
        ("streak", "🔥", "坚持不懈", [3, 7, 30], "天连续", streak),
        ("correct", "✅", "做题能手", [10, 50, 200], "题做对", int(total_correct)),
        ("mastered", "⭐", "融会贯通", [5, 20, 50], "个知识点掌握", int(mastered)),
        ("effort", "💪", "真努力", [5, 20, 60], "次有效努力", int(effort)),
    ]
    out = []
    for aid, icon, name, tiers, unit, val in defs:
        level = sum(1 for t in tiers if val >= t)
        out.append(
            {
                "id": aid,
                "icon": icon,
                "name": name,
                "unit": unit,
                "value": val,
                "level": level,
                "max_level": len(tiers),
                "next_target": tiers[level] if level < len(tiers) else None,
            }
        )
    return {"achievements": out}


def _league_tier(pct: float) -> str:
    """百分位 → 匿名段位（SDT 归属，无 PII）。"""
    if pct >= 90:
        return "钻石"
    if pct >= 70:
        return "黄金"
    if pct >= 40:
        return "白银"
    return "青铜"


@app.get("/v1/league/{student_id}")
async def get_league(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """匿名同年级联赛（SDT 归属）：仅返回本人在同年级中的百分位/段位/队列人数，
    不含任何他人身份或分数（合规：未成年不暴露真实排名/PII）。"""
    from oprim import compute_peer_percentile

    grade = (
        await db.execute(select(User.grade).where(User.id == student_id))
    ).scalar_one_or_none()

    # 同年级学生的"已掌握 KU 数"作为联赛指标（努力/掌握代理，非绝对分数）
    counts_stmt = (
        select(KCMastery.student_id, func.count().label("n"))
        .join(User, User.id == KCMastery.student_id)
        .where(
            User.role == UserRole.student,
            User.deleted_at.is_(None),
            KCMastery.p_mastery >= _MASTERED,
        )
    )
    if grade:
        counts_stmt = counts_stmt.where(User.grade == grade)
    counts_stmt = counts_stmt.group_by(KCMastery.student_id)
    rows = (await db.execute(counts_stmt)).all()

    peer_values = [float(n) for _, n in rows]
    my_value = float(next((n for sid, n in rows if sid == student_id), 0))
    # 队列里没有别人（或本人无掌握）时给中位，避免误导
    if len(peer_values) < 2:
        return {
            "grade": grade,
            "cohort_size": len(peer_values),
            "my_mastered": int(my_value),
            "percentile": None,
            "tier": None,
            "note": "同年级样本不足，暂无排名",
        }
    res = compute_peer_percentile(my_value, peer_values)
    pct = round(float(res.percentile), 1)
    return {
        "grade": grade,
        "cohort_size": len(peer_values),
        "my_mastered": int(my_value),
        "percentile": pct,
        "tier": _league_tier(pct),
    }


@app.get("/v1/learner-model/{student_id}/{kc_id}")
async def get_learner_model(
    student_id: UUID,
    kc_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """开放学习者模型(OLM，教育理念 03)：把 KT 模型**透明摊给学生自己看**以促元认知。
    返回长期掌握 P(L)、此刻可提取性 R、有效掌握、错因画像(粗心 vs 没学会)、下次复习。
    "协商挑战"（我觉得我会了→做一题验证）复用现有 practice/submit，本端点只做透明读。"""
    from oprim import KCState
    from oprim._cognitive import bkt_error_weights
    from oprim.fsrs_engine import fsrs_retrievability

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == kc_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"kc_id": kc_id, "started": False}

    pm = row.p_mastery or 0.0
    card = row.fsrs_card_json
    r_val = fsrs_retrievability(card_dict=card) if card else None
    effective = round(pm * r_val, 4) if r_val is not None else round(pm, 4)

    state = KCState(
        kc_id=kc_id,
        p_init=row.p_init,
        p_transit=row.p_transit,
        p_guess=row.p_guess,
        p_slip=row.p_slip,
        p_mastery=pm,
        p_recognition=row.p_recognition,
        p_recognition_init=row.p_recognition_init,
        long_term_mastery=row.long_term_mastery,
        last_interaction_ts=row.last_interaction_at,
        n_attempts=row.n_attempts or 0,
    )
    careless_w, dontknow_w = bkt_error_weights(state=state)
    tot = (careless_w + dontknow_w) or 1.0

    return {
        "kc_id": kc_id,
        "started": True,
        "p_mastery": round(pm, 4),  # 长期 P(L)
        "retrievability": round(r_val, 4)
        if r_val is not None
        else None,  # 此刻可提取性
        "effective_mastery": effective,  # P(L)×R
        "recognition": round(row.p_recognition, 4) if row.p_recognition else None,
        # 错因画像：粗心(会但错) vs 没学会
        "error_profile": {
            "careless": round(careless_w / tot, 3),
            "dontknow": round(dontknow_w / tot, 3),
        },
        "attempts": row.n_attempts or 0,
        "next_review": card.get("due") if card else None,
        "last_interaction": row.last_interaction_at.isoformat()
        if row.last_interaction_at
        else None,
    }


class ExamDateReq(BaseModel):
    exam_date: Optional[date] = None  # None 清除


@app.post("/v1/users/{student_id}/exam-date")
async def set_exam_date(
    student_id: UUID,
    body: ExamDateReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置本人考试日期（教育理念 06 考期感知）。临考(≤14天)日计划停推新知、向巩固倾斜。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人考试日期")
    await db.execute(
        update(User).where(User.id == student_id).values(exam_date=body.exam_date)
    )
    await db.commit()
    countdown = (body.exam_date - date.today()).days if body.exam_date else None
    return {
        "exam_date": body.exam_date.isoformat() if body.exam_date else None,
        "exam_countdown_days": countdown,
    }


@app.get("/v1/affect/{student_id}")
async def get_affect(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """情感感知（教育理念 08）：从近 12 次作答的**行为信号**估计情感态(挫败/脱离/心流/中性)
    + 自适应建议。启发式，无生物特征采集。"""
    from oprim.affect import affect_estimate

    rows = (
        await db.execute(
            select(
                InteractionEvent.is_correct,
                InteractionEvent.time_spent_seconds,
            )
            .where(InteractionEvent.student_id == student_id)
            .order_by(InteractionEvent.occurred_at.desc())
            .limit(12)
        )
    ).all()
    if not rows:
        return {"state": "neutral", "adaptation": "keep", "n": 0}

    # 最近在前：算尾部连错/连对、快速做对（用可得的 is_correct/time_spent 行为信号）
    consecutive_wrong = 0
    for is_c, _t in rows:
        if is_c is False:
            consecutive_wrong += 1
        else:
            break
    correct_streak = 0
    for is_c, _t in rows:
        if is_c is True:
            correct_streak += 1
        else:
            break
    # 快速放弃代理：做错且用时极短（<8s）视为 give-up
    give_ups = [1 for c, t in rows if c is False and t is not None and t < 8]
    give_up_rate = len(give_ups) / len(rows)
    fast_times = [t for c, t in rows if c is True and t is not None]
    fast_correct = bool(fast_times) and (sum(fast_times) / len(fast_times)) < 30.0

    est = affect_estimate(
        consecutive_wrong=consecutive_wrong,
        give_up_rate=give_up_rate,
        recent_correct_streak=correct_streak,
        fast_correct=fast_correct,
    )
    return {**est, "n": len(rows)}


class PracticeSubmitReq(BaseModel):
    question_id: UUID  # 公共题库行（student_id IS NULL）
    student_id: UUID
    student_answer: str = ""
    is_correct: Optional[bool] = (
        None  # None=先让后端自动判；自由作答判不了时再带自评二次提交
    )
    ku_id: str  # 对应知识单元 ID
    interleaved: bool = False  # 该题是否来自交错(混合KC)复习；True 才训练识别维度 p_recognition (M-G §4.5)
    predicted_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0
    )  # JOL：作答前自评把握，供校准(努力错觉)分析
    self_explanation: Optional[str] = Field(
        default=None, max_length=2000
    )  # 自我解释(Chi 效应,教育理念 04)：学生"为什么这么做"，纯采集
    student_steps: Optional[list[str]] = Field(
        default=None
    )  # 解题步骤(教育理念 07·刻意练习)：答错时确定性定位首个错步


@app.post("/v1/practice/submit")
async def post_practice_submit(
    body: PracticeSubmitReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/practice/submit — 提交专题练习答案。仅学生本人可提交。

    学生做完一道题库题后调此接口：
    - 答错 → 写入该生 wrong_questions（不污染公共题库）
    - 调 cognitive_service.process_interaction 更新 BKT/FSRS
    - 返回掌握度更新结果
    """
    _ensure_student_self(current_user, body.student_id)
    # 1. 读公共题库行，确认 student_id IS NULL
    bank_q = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id == body.question_id, WrongQuestion.student_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not bank_q:
        raise HTTPException(status_code=404, detail="公共题库题目不存在")
    correct_ans = (
        bank_q.correct_answer or ""
    )  # 先取出，避免 commit 后对象过期触发懒加载(MissingGreenlet)

    # 2. 自动判分（选择题/短答确定性判对错；自由作答判 unsure → 交学生对照答案自评）
    from oprim.answer_judge import judge_answer

    verdict = judge_answer(body.student_answer or "", correct_ans)["verdict"]
    auto_judged = verdict in ("correct", "wrong")
    if auto_judged:
        is_correct = verdict == "correct"
    elif body.is_correct is not None:
        is_correct = body.is_correct  # 第二次提交：带学生自评
    else:
        # 判不了 + 学生还没自评 → 揭示答案让其自评，先不落库
        return {
            "needs_self_grade": True,
            "auto_judged": False,
            "is_correct": None,
            "correct_answer": correct_ans,
            "p_mastery": None,
            "mastery_color": _mastery_color(None),
            "feedback": None,
        }

    # 3. 答错则写学生错题记录
    student_wq_id: Optional[UUID] = None
    if not is_correct:
        student_wq = WrongQuestion(
            id=uuid.uuid4(),
            student_id=body.student_id,
            subject=bank_q.subject,
            question_text=bank_q.question_text,
            student_answer=body.student_answer or None,
            correct_answer=bank_q.correct_answer,
            knowledge_points=bank_q.knowledge_points or {body.ku_id: body.ku_id},
            needs_image=bank_q.needs_image,
        )
        db.add(student_wq)
        student_wq_id = student_wq.id
        await db.flush()

    # 4. BKT/FSRS 更新
    result = await process_interaction(
        db,
        student_id=body.student_id,
        kc_id=body.ku_id,
        is_correct=is_correct,
        question_id=bank_q.id,
        source="review",
        is_interleaved=body.interleaved,
        predicted_confidence=body.predicted_confidence,
        self_explanation=body.self_explanation,
    )
    await db.commit()

    # 刻意练习细颗粒反馈（教育理念 07）：答错且带步骤时，确定性定位首个错步（非整题重来）
    step_analysis = None
    if not is_correct and body.student_steps:
        from oskill import verify_steps_chain

        chain = verify_steps_chain(body.student_steps)
        step_analysis = {
            "first_wrong_step": chain.get("first_wrong_step"),  # 0-based；None=未定位
            "step_verdicts": chain.get("step_verdicts"),
        }

    return {
        "is_correct": is_correct,
        "auto_judged": auto_judged,
        "needs_self_grade": False,
        "correct_answer": correct_ans,
        "wrong_question_id": str(student_wq_id) if student_wq_id else None,
        "p_mastery": result.get("p_mastery"),
        "mastery_color": _mastery_color(result.get("p_mastery")),
        "feedback": result.get("feedback"),
        "growth_message": result.get("growth_message"),  # 成长型措辞(05)
        "step_analysis": step_analysis,  # 首错步定位(07)
    }


class SocraticForKuReq(BaseModel):
    ku_id: str
    student_id: UUID


@app.post("/v1/socratic/start-for-ku")
async def post_socratic_start_for_ku(
    body: SocraticForKuReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/socratic/start-for-ku — 为某 KU 知识点发起苏格拉底引导。仅学生本人。

    自动创建一个临时 wrong_question（知识点讲解入口），再调 start_session。
    """
    _ensure_student_self(current_user, body.student_id)
    # 查 KU 信息
    row = (
        await db.execute(
            select(KnowledgeUnit, KnowledgeCluster)
            .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
            .where(KnowledgeUnit.id == body.ku_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    ku, kc = row

    # 创建引导用的 WrongQuestion（没有 paper_id，学生侧记录）
    q_text = f"【{ku.name}】\n{ku.description or ''}"
    wq = WrongQuestion(
        id=uuid.uuid4(),
        student_id=body.student_id,
        subject="math",
        question_text=q_text,
        knowledge_points={body.ku_id: ku.name},
        needs_image=False,
    )
    db.add(wq)
    await db.flush()

    result = await start_session(db, wq.id, body.student_id)
    await db.commit()
    return result


# ===== §J.1 纵向分析 =====


@app.get("/v1/patterns/{student_id}")
async def get_patterns(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/patterns/{student_id} — 个人学习模式分析。"""
    from oskill.longitudinal_pattern import AttemptRecord, longitudinal_pattern

    events = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == student_id)
                .order_by(InteractionEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )
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
            {
                "kc_id": t.kc_id,
                "trend": round(t.trend, 4),
                "current_accuracy": round(t.current_accuracy, 4),
                "is_forgetting": t.is_forgetting,
                "is_plateau": t.is_plateau,
            }
            for t in result.kc_trajectories.values()
        ],
    }


# ===== §K.1 档案导出 =====


@app.get("/v1/parent/export/{student_id}")
async def get_export(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/export/{student_id} — 导出学生学习档案 JSON。"""
    user = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    mastery = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )
    events = (
        (
            await db.execute(
                select(InteractionEvent).where(
                    InteractionEvent.student_id == student_id
                )
            )
        )
        .scalars()
        .all()
    )
    archive = {
        "student_id": str(student_id),
        "name": user.name,
        "kc_mastery": [
            {"kc_id": r.knowledge_point, "p_mastery": round(r.p_mastery or 0, 4)}
            for r in mastery
        ],
        "interaction_count": len(events),
    }
    content = json.dumps(archive, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=archive_{student_id}.json"
        },
    )


# ===== §K.2 用户删除（合规） =====


@app.post("/v1/parent/delete-request/{student_id}")
async def post_delete_request(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/parent/delete-request/{student_id} — 软删除学生数据（合规红线）。
    鉴权：仅学生本人或其绑定家长可操作。"""
    if current_user.id != student_id:
        link = (
            await db.execute(
                select(ParentStudent).where(
                    ParentStudent.parent_id == current_user.id,
                    ParentStudent.student_id == student_id,
                )
            )
        ).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=403, detail="无权删除该学生数据")
    user = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    now = datetime.now(timezone.utc)
    await db.execute(update(User).where(User.id == student_id).values(deleted_at=now))
    await db.commit()
    return {"ok": True, "deleted_at": now.isoformat(), "student_id": str(student_id)}


# ===== §G.2 家长预警 =====


def _ensure_parent_self(current_user: User, parent_id: UUID) -> None:
    """家长身份调用时 parent_id 必须是本人——防止绑定家长冒用他人 parent_id 读写预警。
    学生本人（已过 require_student_access，是预警的数据主体）放行。"""
    if current_user.role == UserRole.parent and current_user.id != parent_id:
        raise HTTPException(status_code=403, detail="parent_id 与当前用户不符")


@app.get("/v1/parent/alerts/{student_id}")
async def get_alerts(
    student_id: UUID,
    parent_id: UUID = Query(...),
    _auth: User = Depends(require_student_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/alerts/{student_id} — 家长预警列表。"""
    _ensure_parent_self(current_user, parent_id)
    return await get_student_alerts(db, student_id, parent_id)


@app.post("/v1/parent/alerts/{student_id}/check")
async def post_run_alert_checks(
    student_id: UUID,
    parent_id: UUID = Query(...),
    _auth: User = Depends(require_student_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/parent/alerts/{student_id}/check — 立即执行 5 类预警检查。"""
    _ensure_parent_self(current_user, parent_id)
    result = await run_alert_checks(db, student_id, parent_id)
    await db.commit()
    return {"checked": len(result), "alerts": result}


# ===== §D.4 单题快录 =====


@app.post("/v1/papers/quick")
async def post_quick_question(
    student_id: UUID = Query(...),
    kc_hint: Optional[str] = Query(None),
    file: UploadFile = File(...),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/papers/quick — 单题快录，立即创建 WrongQuestion。鉴权：学生本人或绑定家长。"""
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
            student_id=current_user.id, image_b64=image_b64, kc_hint=kc_hint
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
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/review/due/{student_id}
    获取到期的变式复习题。鉴权：学生本人或绑定家长（原先任意家长可读）。
    """
    await _ensure_student_access(db, current_user, student_id)

    items = await get_due_variants(db, student_id)
    return items


@app.post("/v1/review/reveal/{student_id}")
async def post_review_reveal(
    student_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检索练习红线：揭示复习答案 = 放弃检索 → 记 FSRS Again，再返回答案。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    kc_id = payload.get("kc_id")
    if not kc_id:
        raise HTTPException(status_code=422, detail="kc_id required")
    from services.review_service import reveal_review_answer

    result = await reveal_review_answer(db, student_id, kc_id)
    await db.commit()
    return result


@app.post("/v1/review/submit/{student_id}")
async def post_review_submit(
    student_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交复习作答（先检索后核对）：确定性判分入 BKT/FSRS，返回参考答案。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    kc_id = payload.get("kc_id")
    if not kc_id:
        raise HTTPException(status_code=422, detail="kc_id required")
    from services.review_service import submit_review_answer

    result = await submit_review_answer(
        db, student_id, kc_id, str(payload.get("answer", ""))
    )
    await db.commit()
    return result


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
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/error-journal/{student_id}
    错题本主动入口。鉴权：学生本人或绑定家长（原先任意家长可读）。
    """
    await _ensure_student_access(db, current_user, student_id)

    # 1. Get distribution
    pool = await get_pg_pool()
    dist = await get_error_distribution(pool, student_id, kc_id)

    # 2. Get detailed wrong questions
    # Layer 4 query
    stmt = select(WrongQuestion).where(WrongQuestion.student_id == student_id)
    if kc_id:
        stmt = stmt.where(WrongQuestion.knowledge_points.has_key(kc_id))
    # Note: error_type filtering would require error_tag join if not in wrong_questions

    stmt = stmt.order_by(WrongQuestion.created_at.desc())
    all_rows = (await db.execute(stmt)).scalars().all()

    # 按题干去重：同一道题错多次合并成一条（计 wrong_count），保留最新一次
    seen: dict[str, dict] = {}
    for r in all_rows:
        key = (r.question_text or "").strip() or str(r.id)
        if key in seen:
            seen[key]["wrong_count"] += 1
        else:
            kid = (
                list(r.knowledge_points.keys())[0] if r.knowledge_points else "unknown"
            )
            seen[key] = {"row": r, "kc_id": kid, "wrong_count": 1}
    deduped = list(seen.values())  # dict 保序；all_rows 已按时间倒序
    page = deduped[offset : offset + limit]

    real_ids = {d["kc_id"] for d in page if d["kc_id"] != "unknown"}
    name_map: dict[str, str] = {}
    if real_ids:
        krows = (
            await db.execute(
                select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                    KnowledgeUnit.id.in_(real_ids)
                )
            )
        ).all()
        name_map = {kid: nm for kid, nm in krows}

    res = []
    for d in page:
        r, kid = d["row"], d["kc_id"]
        _name = name_map.get(kid)
        if not _name:
            _kcd = get_kc(kid)
            _name = (_kcd.get("name") if _kcd else None) or kid
        res.append(
            {
                "question_id": str(r.id),
                "kc_id": kid,
                "kc_name": _name,
                "question_text": r.question_text or "",
                "student_answer": r.student_answer or "",
                "correct_answer": r.correct_answer or "",
                "error_tag": (r.error_type.value if r.error_type else "unknown"),
                "wrong_at": r.created_at.isoformat(),
                "wrong_count": d["wrong_count"],
                "can_practice_variant": True,
            }
        )

    return {"distribution": dist, "items": res}


# ===== §Essay Guide =====

from oskill import essay_guide, EssayGuideInput


class EssayGuideRequest(BaseModel):
    essay_text: str
    grade: str
    essay_type: str


@app.post("/v1/essay/guide")
async def post_essay_guide(
    req: EssayGuideRequest, current_user: User = Depends(get_current_user)
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
            requirements=f"Grade: {req.grade}, Type: {req.essay_type}",
        ),
        caller=caller,
    )

    return {
        "rubric_scores": res.feedback,
        "guidance_questions": res.suggested_questions,
        "is_completed": res.is_completed,
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
    req: SpeakingPracticeRequest, current_user: User = Depends(get_current_user)
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
    }


@app.get("/v1/speaking/history/{student_id}")
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
    仅会话归属学生本人可继续。
    """
    await _ensure_session_owner(db, current_user, session_id)

    async def event_stream():
        async for chunk in force_analysis_message_stream(db, session_id, message):
            yield chunk

    from fastapi.responses import StreamingResponse

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ===== §M.5 阅读理解引导（英语/语文）=====

from services.reading_guide_service import (
    start_reading_guide,
    reading_guide_message_stream,
)


class ReadingGuideStartReq(BaseModel):
    article_text: str
    question: str
    subject: str = "chinese"


@app.post("/v1/reading/guide/start")
async def post_reading_guide_start(
    body: ReadingGuideStartReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/reading/guide/start — 开始阅读理解引导会话。

    subject: "chinese" 或 "english"。文章正文走 body（可能很长）。返回开场引导问（不含答案）。
    """
    result = await start_reading_guide(
        db, body.article_text, body.question, body.subject, current_user.id
    )
    return result


@app.post("/v1/reading/guide/message")
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
    storage_path = (
        f"{'platform' if is_platform else str(current_user.id)}/{file_id}.{ext}"
    )

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

    # item 7：平台预置教材（有 textbook_id）上传后触发可信知识抽取（异步）。
    #   学生自传资料无 textbook 归属，不灌权威课程库（避免污染）。
    extraction_triggered = False
    if textbook_id:
        try:
            from tasks.textbook_tasks import extract_textbook_file_task

            extract_textbook_file_task.delay(file_id)
            extraction_triggered = True
        except Exception:
            pass  # broker 不可用不应阻断上传

    return {
        "file_id": file_id,
        "filename": filename,
        "file_type": ext,
        "file_size": len(data),
        "storage_path": storage_path,
        "extraction_triggered": extraction_triggered,
    }


# ── 文件列表 ─────────────────────────────────────────────────────────


@app.get("/v1/textbook-files/{file_id}/meta")
async def get_textbook_file_meta(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/textbook-files/{file_id}/meta — 单个文件元数据（供阅读器初始化用）。
    平台预置文件（owner_student_id IS NULL）所有认证用户可查。
    """
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")
    return {
        "file_id": tf.id,
        "textbook_id": tf.textbook_id,
        "owner_student_id": str(tf.owner_student_id) if tf.owner_student_id else None,
        "filename": tf.filename,
        "file_type": tf.file_type,
        "file_size": tf.file_size,
        "has_text_layer": tf.has_text_layer,
        "uploaded_at": tf.uploaded_at.isoformat(),
    }


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
        stmt = (
            select(TextbookFile)
            .where(
                or_(
                    (TextbookFile.textbook_id == textbook_id)
                    & (TextbookFile.owner_student_id == None),  # noqa: E711
                    (TextbookFile.textbook_id == textbook_id)
                    & (TextbookFile.owner_student_id == current_user.id),
                )
            )
            .order_by(TextbookFile.uploaded_at.desc())
        )
    else:
        # 不传 textbook_id：当前学生自传的所有文件（含无 textbook_id 的）
        stmt = (
            select(TextbookFile)
            .where(TextbookFile.owner_student_id == current_user.id)
            .order_by(TextbookFile.uploaded_at.desc())
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "file_id": r.id,
            "textbook_id": r.textbook_id,
            "owner_student_id": str(r.owner_student_id) if r.owner_student_id else None,
            "filename": r.filename,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "has_text_layer": r.has_text_layer,
            "uploaded_at": r.uploaded_at.isoformat(),
        }
        for r in rows
    ]


# ── 平台教材库 ──────────────────────────────────────────────────────

_SUBJECT_ORDER = ["math", "physics", "chinese", "english", "history"]
_SUBJECT_NAMES = {
    "math": "数学",
    "physics": "物理",
    "chinese": "语文",
    "english": "英语",
    "history": "历史",
}


def _grade_sort_key(grade: str) -> int:
    m = re.match(r"G(\d+)$", grade)
    if m:
        return int(m.group(1))
    # "高一/高二/高三" → G10/G11/G12
    for hs, n in [("高一", 10), ("高二", 11), ("高三", 12)]:
        if grade.startswith(hs):
            return n
    # "初一/初二/初三" → G7/G8/G9
    for ms, n in [("初一", 7), ("初二", 8), ("初三", 9)]:
        if grade.startswith(ms):
            return n
    return 99


@app.get("/v1/library/textbooks")
async def list_library_textbooks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/library/textbooks
    返回所有平台预置教材（owner_student_id IS NULL），按学科分组，每科内按年级排序。
    过滤测试条目（textbook_id LIKE 'tb-lp-%' 或 book_name='练习教材'）。
    """
    stmt = (
        select(TextbookFile, Textbook)
        .join(Textbook, TextbookFile.textbook_id == Textbook.id)
        .where(
            TextbookFile.owner_student_id == None,  # noqa: E711
            ~Textbook.id.like("tb-lp-%"),
            Textbook.book_name != "练习教材",
        )
    )
    rows = (await db.execute(stmt)).all()

    grouped: dict[str, list] = {s: [] for s in _SUBJECT_ORDER}
    for tf, tb in rows:
        if tb.subject not in grouped:
            continue
        grouped[tb.subject].append(
            {
                "textbook_id": tb.id,
                "book_name": tb.book_name,
                "grade": tb.grade,
                "edition": tb.edition,
                "file_id": tf.id,
                "has_text_layer": tf.has_text_layer,
            }
        )

    subjects = []
    for subject in _SUBJECT_ORDER:
        books = sorted(grouped[subject], key=lambda x: _grade_sort_key(x["grade"]))
        subjects.append(
            {
                "subject": subject,
                "name": _SUBJECT_NAMES[subject],
                "textbooks": books,
            }
        )

    return {"subjects": subjects}


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
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == file_id))
    ).scalar_one_or_none()
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
    import urllib.parse

    safe_name = urllib.parse.quote(tf.filename, safe="")
    return Response(
        content=data,
        media_type=ct,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
        },
    )


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
    tf = (
        await db.execute(select(TextbookFile).where(TextbookFile.id == body.file_id))
    ).scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 仅 owner 或平台预置文件可高亮
    if tf.owner_student_id is not None and tf.owner_student_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    if body.color not in ("yellow", "green", "blue", "red"):
        raise HTTPException(
            status_code=400, detail="color 必须是 yellow/green/blue/red 之一"
        )

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
    hl = (
        await db.execute(
            select(Highlight).where(
                Highlight.id == highlight_id, Highlight.student_id == current_user.id
            )
        )
    ).scalar_one_or_none()
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
    hl = (
        await db.execute(
            select(Highlight).where(
                Highlight.id == highlight_id, Highlight.student_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if not hl:
        raise HTTPException(status_code=404, detail="高亮不存在")
    # 解除 reading_notes 的外键引用，再删除
    await db.execute(
        update(ReadingNote)
        .where(ReadingNote.highlight_id == highlight_id)
        .values(highlight_id=None)
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
        hl = (
            await db.execute(
                select(Highlight).where(
                    Highlight.id == body.highlight_id,
                    Highlight.student_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
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
    stmt = select(ReadingNote).where(
        ReadingNote.student_id == current_user.id,
        ReadingNote.deleted_at == None,  # noqa: E711
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
    rn = (
        await db.execute(
            select(ReadingNote).where(
                ReadingNote.id == note_id,
                ReadingNote.student_id == current_user.id,
                ReadingNote.deleted_at == None,  # noqa: E711
            )
        )
    ).scalar_one_or_none()
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
    rn = (
        await db.execute(
            select(ReadingNote).where(
                ReadingNote.id == note_id,
                ReadingNote.student_id == current_user.id,
                ReadingNote.deleted_at == None,  # noqa: E711
            )
        )
    ).scalar_one_or_none()
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


# ── 前端静态文件（SPA，最后挂载） ─────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    # 构建产物（哈希文件名）走 StaticFiles；其余任意路径回退 index.html 支持 SPA 客户端路由
    app.mount(
        "/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # 未匹配的 API 路径仍返回 404，不要吞掉
        if full_path.startswith(
            ("v1/", "v1", "health", "docs", "redoc", "openapi.json")
        ):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")

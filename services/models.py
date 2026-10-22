import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Float,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 单源在 obase（3O 可 import，无需反向依赖 services）
from obase.domain_enums import ErrorType as ErrorType


class Base(DeclarativeBase):
    pass


# ===== Enums =====
class UserRole(str, enum.Enum):
    student = "student"
    parent = "parent"


class PaperStatus(str, enum.Enum):
    processing = "processing"
    done = "done"
    failed = "failed"


class StorageTier(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"
    archived = "archived"


class InteractionSource(str, enum.Enum):
    paper = "paper"
    quick = "quick"
    review = "review"
    socratic = "socratic"
    probe = "probe"  # 保留探针：远未到期的稳定卡混入复习队列，实测召回 vs 预测 R
    # U.18 迁移探针：已掌握 KU 现场生成的全新核验变式（不落库/不进练习池），
    # 混入复习队列测"同 KU 新实例迁移"（near transfer；非跨 KU 远迁移，见 transfer_probe_service）。
    transfer_probe = "transfer_probe"
    # T.10 非数学接入认知主线：physics/reading/speaking 会话结果回写 process_interaction。
    force_analysis = "force_analysis"
    reading_guide = "reading_guide"
    speaking = "speaking"
    # T.8 周期限时小测（检索检查点）。
    quiz = "quiz"
    # FIRe-lite 前置信用回写（M-H §4.8）：综合题答对顺延前置 due 的记账事件。
    # 非真实作答：不进 BKT/FSRS 重放/校准/学习量统计，且不得再触发 FIRe（不级联）。
    fire_credit = "fire_credit"
    # U.19 英语习得型范式：词汇 FSRS 复现卡片作答（认识/不认识），复用既有
    # KCMastery/process_interaction 通用字符串 knowledge_point 机制，不新建调度表。
    vocab_review = "vocab_review"
    # Immersive Learning：视频/听写/理解练习的 performance Evidence 经 Memory Router
    # 进入同一 process_interaction 写路径（禁止第二套 scheduler）。
    immersive = "immersive"


class SocraticMode(str, enum.Enum):
    deep = "deep"
    mixed = "mixed"
    sprint = "sprint"
    force_analysis = "force_analysis"
    reading_guide = "reading_guide"
    concept_diagnosis = "concept_diagnosis"


class SocraticOutcome(str, enum.Enum):
    success = "success"
    partial = "partial"
    failed = "failed"
    abandoned = "abandoned"


class MissionType(str, enum.Enum):
    review = "review"
    socratic = "socratic"
    upload = "upload"
    knowledge_focus = "knowledge_focus"


class AlertType(str, enum.Enum):
    emotion = "emotion"
    score_drop = "score_drop"
    task_missing = "task_missing"
    time_drop = "time_drop"
    late_night = "late_night"


class AlertLevel(str, enum.Enum):
    notice = "notice"
    attention = "attention"
    important = "important"


# ===== 用户与合规 =====
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    phone: Mapped[Optional[str]] = mapped_column(String(11), unique=True)
    # 邮箱注册（新主标识）：唯一可空——老用户手机号注册无 email，新用户邮箱注册无 phone。
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True)
    role: Mapped[UserRole] = mapped_column(nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(40))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    exam_date: Mapped[Optional[date]] = mapped_column(Date)  # 考期感知(06)
    share_process_with_parent: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )  # L6 隐私分层
    invite_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True)
    # 可选密码登录：bcrypt 哈希。NULL = 未设密码，该账号只走手机/邮箱验证码。
    # 绝不进任何响应体——auth_service 的 user 字典全部手工构造（不序列ORM对象），
    # 改动那里时务必继续显式列字段。见 alembic b7c8d9e0f1a2。
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    # U.23 UDL 无障碍：字体/行距/配色/低带宽偏好，跨设备持久化。渲染在 mneme-web
    # 前端，这里只存偏好 + 供后端按需裁剪响应（低带宽模式）。默认空={} = 未设置，
    # 前端按各自默认值展示，不代表"无障碍"。
    accessibility_prefs: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # V.2 每日计划参数可见+可配置：budget_minutes/late_night_hour/minute/weak_max_items/
    # new_max_items，学生可调；GATE(掌握度阈值)单源不在此列，见 daily_plan_prefs_service.py。
    daily_plan_prefs: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # N.4 用户教材绑定：{subject: textbook_id}，学生按学科分别绑（一个学科可能有
    # 多本教材，单列存不下）。未绑定学科=该 key 不存在=向后兼容，回退全教材混排。
    textbook_bindings: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ParentStudent(Base):
    __tablename__ = "parent_student"

    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    nickname: Mapped[Optional[str]] = mapped_column(String(20))
    display_order: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class GuardianConsent(Base):
    __tablename__ = "guardian_consents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    guardian_phone: Mapped[Optional[str]] = mapped_column(String(11))
    # 邮箱注册的<14监护同意：监护人邮箱（手机号注册走 guardian_phone，二选一）
    guardian_email: Mapped[Optional[str]] = mapped_column(String(254))
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))


class RegistrationInvite(Base):
    """Admin-issued, single-use student registration invite (invite-only launch).

    ``student_id``/``used_at`` mark redemption. Codes are never emailed by the
    platform: an admin hands them out out-of-band, so registration no longer
    depends on a working SMTP/SMS provider.
    """

    __tablename__ = "registration_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(120))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    # 兑换该码的学生（未成年人数据 → 必须同 PR 入 purge_service._STUDENT_TABLES）
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== 学习数据 =====
class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    subject: Mapped[Optional[str]] = mapped_column(String(20), server_default="math")
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    image_urls: Mapped[Optional[dict]] = mapped_column(JSONB)
    ocr_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    status: Mapped[Optional[PaperStatus]] = mapped_column(
        server_default=PaperStatus.processing.value
    )
    storage_tier: Mapped[Optional[StorageTier]] = mapped_column(
        server_default=StorageTier.hot.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WrongQuestion(Base):
    __tablename__ = "wrong_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    paper_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    subject: Mapped[Optional[str]] = mapped_column(String(20), server_default="math")
    question_text: Mapped[Optional[str]] = mapped_column(Text)
    student_answer: Mapped[Optional[str]] = mapped_column(Text)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text)
    knowledge_points: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_type: Mapped[Optional[ErrorType]] = mapped_column()
    profiler_analysis: Mapped[Optional[dict]] = mapped_column(JSONB)
    fsrs_card_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    fsrs_due: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fsrs_state: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ku_match_meta: Mapped[Optional[dict]] = mapped_column(JSONB)
    needs_image: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    step_analysis: Mapped[Optional[dict]] = mapped_column(
        JSONB
    )  # T.6 步骤链批改：{student_steps, step_verdicts, first_wrong_step(0-based|null)}
    # ZPD 难度自适应排序用（迁移 8ad19eb4ab90）：未校准(NULL)时按 999.0 距离兜底
    item_difficulty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 错题本复习（迁移 qrc1a2b3c4d5，全部可空/有默认值 = 纯增量）：
    # source 记这道错题从哪来（practice/quiz/review/photo_ask/mcp/manual…）；
    # image_key 是私有桶 question-images 里的对象键（只存键，不存签名 URL）；
    # review_* 是 10 分钟错题复习的毕业计数（连续答对 N 次且间隔够长 → graduated_at）。
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    image_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    question_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    review_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    review_correct_streak: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    graduated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class QuestionRecord(Base):
    """学生见到/作答的每一道题（统一、只追加的做题记录；迁移 qrc1a2b3c4d5）。

    只追加：不删、不改题目事实（题干/作答/判分）；仅回填关联与反馈列
    （wrong_question_id、understood、hints_used、meta.solution 等）。拍照提问在识别后先落一行
    （is_correct 为空），学生确认/修改题干后回填 question_text。
    student_id / wrong_question_id 只存值不设 FK：记录写在独立会话里，不能等主事务里未提交的
    错题行；学生硬删由 purge_service._STUDENT_TABLES 清单负责（同 question_bookmarks）。
    """

    __tablename__ = "question_records"
    __table_args__ = (
        Index("ix_question_records_student_created", "student_id", "created_at"),
        Index("ix_question_records_student_source", "student_id", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # 不设 FK（同 question_bookmarks）：学生硬删走 purge_service._STUDENT_TABLES 清单。
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    kc_ids: Mapped[Optional[list]] = mapped_column(JSONB(none_as_null=True), nullable=True)
    question_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    question_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    student_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    grader: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hints_used: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    understood: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    wrong_question_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    meta: Mapped[Optional[dict]] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ===== 认知状态（内核落库）=====
class KCMastery(Base):
    __tablename__ = "kc_mastery"
    __table_args__ = (UniqueConstraint("student_id", "knowledge_point"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    knowledge_point: Mapped[str] = mapped_column(String(100), nullable=False)
    p_mastery: Mapped[Optional[float]] = mapped_column(Float)
    p_init: Mapped[float] = mapped_column(Float, nullable=False)
    p_transit: Mapped[float] = mapped_column(Float, nullable=False)
    p_guess: Mapped[float] = mapped_column(Float, nullable=False)
    p_slip: Mapped[float] = mapped_column(Float, nullable=False)
    p_recognition: Mapped[Optional[float]] = mapped_column(Float)
    p_recognition_init: Mapped[Optional[float]] = mapped_column(Float)
    long_term_mastery: Mapped[Optional[float]] = mapped_column(Float)
    fsrs_card_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    n_attempts: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    # U.17 掌握裁决题池隔离：与 BKT p_mastery 分离的独立裁决状态，只由
    # mastery_gate_service 现场生成的题目（不落库、不进练习池）判定写入。
    mastery_confirmed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    mastery_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )


class BKTPrior(Base):
    __tablename__ = "bkt_priors"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_point", "question_type", name="uq_bkt_priors_kc_qtype"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject: Mapped[Optional[str]] = mapped_column(String(20))
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(100))
    question_type: Mapped[Optional[str]] = mapped_column(String(20))
    p_init: Mapped[Optional[float]] = mapped_column(Float)
    p_transit: Mapped[Optional[float]] = mapped_column(Float)
    p_guess: Mapped[Optional[float]] = mapped_column(Float)
    p_slip: Mapped[Optional[float]] = mapped_column(Float)
    calibrated_from_n: Mapped[Optional[int]] = mapped_column(
        Integer, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class FSRSWeights(Base):
    """按群体（cohort）从真实复习日志择优出的 FSRS 权重（个性化调度基础设施）。
    parameters=NULL 表示该 cohort 用 FSRS 默认权重最优。"""

    __tablename__ = "fsrs_weights"
    __table_args__ = (UniqueConstraint("cohort", name="uq_fsrs_weights_cohort"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    cohort: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )  # 21 维 FSRS-6 权重
    logloss: Mapped[Optional[float]] = mapped_column(Float)
    n_reviews: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class EvaluationRun(Base):
    """护城河实证监控：每次评估（周任务只读重放 interaction_events）的 AUC/log-loss 落表。
    auc/log_loss 为 NULL 表示样本不足跑不出指标——行仍保留，用于看数据积累进度。"""

    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    n_events: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    n_students: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    auc: Mapped[Optional[float]] = mapped_column(Float)
    log_loss: Mapped[Optional[float]] = mapped_column(Float)
    meta: Mapped[Optional[dict]] = mapped_column(JSONB)  # 分桶结果/verdict/base_rate 等


class ModelRegistry(Base):
    """Versioned model/policy registry for evaluation isolation.

    This table contains model metadata only, not student data.  A registry row
    is valid only when its train/eval windows are ordered and non-overlapping;
    the service layer additionally rejects windows in the future.
    """

    __tablename__ = "model_registry"
    __table_args__ = (
        CheckConstraint(
            "status IN ('shadow', 'candidate', 'production', 'retired')",
            name="ck_model_registry_status",
        ),
        CheckConstraint(
            "train_end <= eval_start AND eval_start < eval_end",
            name="ck_model_registry_time_windows",
        ),
    )

    model_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(80), nullable=False)
    code_sha: Mapped[str] = mapped_column(String(128), nullable=False)
    train_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    train_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    eval_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    eval_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="shadow"
    )
    rollback_to: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )


class InteractionEvent(Base):
    __tablename__ = "interaction_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    knowledge_point: Mapped[str] = mapped_column(String(100), nullable=False)
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source: Mapped[InteractionSource] = mapped_column(nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fsrs_rating: Mapped[Optional[int]] = mapped_column(SmallInteger)
    time_spent_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    days_since_last: Mapped[Optional[float]] = mapped_column(Float)
    is_interleaved: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default="false"
    )
    item_difficulty: Mapped[Optional[float]] = mapped_column(
        Float
    )  # 题目难度 b∈[0,1]（IRT），供 DKT/校准
    predicted_confidence: Mapped[Optional[float]] = mapped_column(
        Float
    )  # JOL：作答前自评把握 ∈[0,1]
    predicted_r: Mapped[Optional[float]] = mapped_column(
        Float
    )  # 保留探针：作答时 FSRS 预测的可提取性 R ∈[0,1]（source=probe 时填）
    fire_meta: Mapped[Optional[dict]] = mapped_column(
        JSONB
    )  # FIRe（source=fire_credit 时填）：{trigger_kc_id, trigger_event_id, kappa, due_before, due_after}
    self_explanation: Mapped[Optional[str]] = mapped_column(
        Text
    )  # 自我解释（Chi 效应，教育理念 04）：学生"为什么这么做"，纯采集不参与判分
    # Evaluation OS：历史事件保持 NULL（未知），不把未标注的迁移事件伪装成 no-AI
    # 证据；新的 Tutor/独立探针路径显式写入这些字段。
    tutor_mode: Mapped[Optional[str]] = mapped_column(String(32))
    ai_assisted: Mapped[Optional[bool]] = mapped_column(Boolean)
    independent_mode: Mapped[Optional[bool]] = mapped_column(Boolean)
    evaluation_phase: Mapped[Optional[str]] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class LearningEventRecord(Base):
    """持久化的 Learning Event v2 事实行。

    该表是 append-only 事实边界；认知状态仍由既有 process_interaction 写入
    ``kc_mastery``，不得把 ``p_mastery`` 或其他 projection 字段塞进这里。
    JSONB 字段保存契约中的嵌套结构，``event_checksum`` 用于幂等重试和冲突检测。
    """

    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_learning_events_event_id"),
        # 未来版本用新表/迁移承载；v2 表不静默接受未知 schema。
        CheckConstraint("schema_version = '2'", name="ck_learning_events_v2"),
        CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_learning_events_privacy_class",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="2"
    )
    # actor 可以是系统/家长/外部主体，不强制绑定 users；student_id 才是
    # 未成年人数据归属与 purge 边界。
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(200), nullable=False)
    content_version: Mapped[Optional[str]] = mapped_column(String(100))
    knowledge_refs: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    item_features: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    response: Mapped[Optional[dict]] = mapped_column(JSONB)
    outcome: Mapped[Optional[dict]] = mapped_column(JSONB)
    process_signals: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metacognitive: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    intervention: Mapped[Optional[dict]] = mapped_column(JSONB)
    evaluation_phase: Mapped[Optional[str]] = mapped_column(String(32))
    provenance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    privacy_class: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="P1"
    )
    trace_id: Mapped[Optional[str]] = mapped_column(String(200))
    supersedes_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True)
    )
    correction_reason: Mapped[Optional[str]] = mapped_column(Text)
    event_checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class MemoryClaim(Base):
    """Evidence-grounded learner-memory claim.

    Claims are projections for explanation and narrative.  They are never the
    source of truth for mastery; a claim must point at one or more immutable
    evidence rows before it can be shown to a learner or guardian.
    """

    __tablename__ = "memory_claims"
    __table_args__ = (
        CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_memory_claims_privacy_class",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_ref: Mapped[Optional[str]] = mapped_column(String(100))
    claim_value: Mapped[Optional[dict]] = mapped_column(JSONB)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    model_version: Mapped[Optional[str]] = mapped_column(String(120))
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    uncertainty: Mapped[Optional[dict]] = mapped_column(JSONB)
    evidence_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="contract"
    )
    privacy_class: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="P1"
    )
    provenance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class MemoryEvidence(Base):
    """A source fact attached to a claim, normally an event or verified result."""

    __tablename__ = "memory_evidence"
    __table_args__ = (
        CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_memory_evidence_privacy_class",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    knowledge_ref: Mapped[Optional[str]] = mapped_column(String(100))
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    weight: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    model_version: Mapped[Optional[str]] = mapped_column(String(120))
    verifier_version: Mapped[Optional[str]] = mapped_column(String(120))
    evidence_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="contract"
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    privacy_class: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="P1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class MemoryClaimEvidence(Base):
    """Many-to-many edge; the edge itself carries no learner PII."""

    __tablename__ = "memory_claim_evidence"
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_claims.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_evidence.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="supports"
    )


class PolicyDecisionRecord(Base):
    """Append-only trace of a policy decision; it is never learner state."""

    __tablename__ = "policy_decisions"
    __table_args__ = (
        CheckConstraint(
            "evidence_level IN ('contract', 'offline', 'observational', 'randomized', 'commercial')",
            name="ck_policy_decisions_evidence_level",
        ),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    candidate_actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    selected_action: Mapped[Optional[dict]] = mapped_column(JSONB)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    state_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expected_utility: Mapped[Optional[float]] = mapped_column(Float)
    exploration_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    fallback_reason: Mapped[Optional[str]] = mapped_column(Text)
    evidence_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="contract"
    )
    trace_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PilotEnrollment(Base):
    """Auditable pilot enrollment metadata without unnecessary learner PII."""

    __tablename__ = "pilot_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "protocol_id",
            "protocol_version",
            name="uq_pilot_enrollments_student_protocol",
        ),
        CheckConstraint(
            "consent_status IN ('UNKNOWN', 'NOT_REQUIRED', 'PENDING', 'GRANTED', 'REVOKED')",
            name="ck_pilot_enrollments_consent_status",
        ),
    )

    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    protocol_id: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(40), nullable=False)
    cohort_id: Mapped[str] = mapped_column(String(120), nullable=False)
    consent_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="UNKNOWN"
    )
    consent_version: Mapped[Optional[str]] = mapped_column(String(40))
    consent_recorded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PilotAssignment(Base):
    """Immutable deterministic/pre-registered assignment metadata."""

    __tablename__ = "pilot_assignments"
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", name="uq_pilot_assignments_enrollment"
        ),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pilot_enrollments.enrollment_id"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    protocol_id: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(40), nullable=False)
    cohort_id: Mapped[str] = mapped_column(String(120), nullable=False)
    arm: Mapped[str] = mapped_column(String(80), nullable=False)
    assignment_method: Mapped[str] = mapped_column(String(120), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PilotMeasurementSchedule(Base):
    """Protocol-versioned delayed measurement window for one student."""

    __tablename__ = "pilot_measurement_schedules"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "protocol_id",
            "protocol_version",
            "phase",
            name="uq_pilot_measurement_student_phase",
        ),
        CheckConstraint(
            "status IN ('SCHEDULED', 'AVAILABLE', 'COMPLETED', 'MISSED', 'INVALIDATED')",
            name="ck_pilot_measurement_status",
        ),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pilot_enrollments.enrollment_id"), nullable=False
    )
    protocol_id: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(40), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_open_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_close_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="SCHEDULED"
    )
    evidence_event_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PilotAnalysisArtifact(Base):
    """Immutable aggregate analysis artifact used to support evidence claims."""

    __tablename__ = "pilot_analysis_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    protocol_id: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(40), nullable=False)
    cohort_id: Mapped[str] = mapped_column(String(120), nullable=False)
    code_sha: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    report: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PilotEvidenceRegistry(Base):
    """Product-level evidence registry; no student identifiers are stored."""

    __tablename__ = "pilot_evidence_registry"
    __table_args__ = (
        CheckConstraint(
            "evidence_level IN ('contract', 'offline', 'observational', 'randomized', 'commercial')",
            name="ck_pilot_evidence_registry_level",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'SUPPORTED', 'NOT_SUPPORTED', 'INCONCLUSIVE', 'RETRACTED')",
            name="ck_pilot_evidence_registry_status",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    protocol_id: Mapped[Optional[str]] = mapped_column(String(120))
    cohort_id: Mapped[Optional[str]] = mapped_column(String(120))
    data_cutoff: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    analysis_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    analysis_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(128), ForeignKey("pilot_analysis_artifacts.artifact_id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class PolicyOutcomeLinkRecord(Base):
    """Append-only edge from a policy decision to its observed outcome."""

    __tablename__ = "policy_outcome_links"
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "action_event_id",
            "outcome_event_id",
            name="uq_policy_outcome_link_edge",
        ),
        CheckConstraint(
            "contamination_status IN ('CLEAN', 'AI_ASSISTED', 'HINT_ASSISTED', 'ANSWER_EXPOSED', 'INVALIDATED', 'UNKNOWN')",
            name="ck_policy_outcome_link_contamination",
        ),
    )

    link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    latency_seconds: Mapped[Optional[float]] = mapped_column(Float)
    eligible_for_evaluation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    contamination_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="UNKNOWN"
    )
    trace_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class LearningOutcomeLedgerRecord(Base):
    """Query projection of LearningEvent outcomes, not a second event store."""

    __tablename__ = "learning_outcome_ledger"
    ledger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_ref: Mapped[Optional[str]] = mapped_column(String(100))
    state_version: Mapped[Optional[str]] = mapped_column(String(120))
    policy_version: Mapped[Optional[str]] = mapped_column(String(120))
    outcome: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evaluation_phase: Mapped[Optional[str]] = mapped_column(String(32))
    evaluation_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="descriptive"
    )
    contamination_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="UNKNOWN"
    )
    protocol_id: Mapped[Optional[str]] = mapped_column(String(120))
    protocol_version: Mapped[Optional[str]] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "contamination_status IN ('CLEAN', 'AI_ASSISTED', 'HINT_ASSISTED', 'ANSWER_EXPOSED', 'INVALIDATED', 'UNKNOWN')",
            name="ck_learning_outcome_ledger_contamination",
        ),
        Index("ix_learning_outcome_ledger_student_time", "student_id", "occurred_at"),
    )


class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "knowledge_point",
            "snapshot_month",
            name="uq_mastery_snapshots_student_kc_month",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(100))
    long_term_mastery: Mapped[Optional[float]] = mapped_column(Float)
    dominant_error_type: Mapped[Optional[str]] = mapped_column(String(20))
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    snapshot_month: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== 机制增强 =====
class SolveCache(Base):
    __tablename__ = "solve_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kc_id: Mapped[Optional[str]] = mapped_column(String(100))
    problem_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    solve_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    solvable: Mapped[Optional[bool]] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class LessonPage(Base):
    __tablename__ = "lesson_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wrong_questions.id")
    )
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    plot_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    diagram_svg: Mapped[Optional[str]] = mapped_column(Text)
    self_check_passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    report_path: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class CornellProgress(Base):
    """康奈尔笔记云端进度（自报 checklist，≠ kc_mastery）。"""

    __tablename__ = "cornell_progress"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    topic_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    state: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class EffortfulGain(Base):
    __tablename__ = "effortful_gains"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    struggle_score: Mapped[Optional[float]] = mapped_column(Float)
    retention_delta: Mapped[Optional[float]] = mapped_column(Float)
    effortful_gain: Mapped[Optional[float]] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== 苏格拉底与目标 =====
class SocraticSession(Base):
    __tablename__ = "socratic_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wrong_questions.id")
    )
    mode: Mapped[Optional[SocraticMode]] = mapped_column()
    messages: Mapped[Optional[dict]] = mapped_column(JSONB)
    emotion_log: Mapped[Optional[dict]] = mapped_column(JSONB)
    outcome: Mapped[Optional[SocraticOutcome]] = mapped_column()
    used_escape_hatch: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default="false"
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DailyMission(Base):
    __tablename__ = "daily_missions"
    __table_args__ = (UniqueConstraint("student_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    date: Mapped[Optional[date]] = mapped_column(Date)
    mission_type: Mapped[Optional[MissionType]] = mapped_column()
    content: Mapped[Optional[dict]] = mapped_column(JSONB)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    interleaved: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    requires_active_recall: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default="false"
    )
    completed: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class TimedQuiz(Base):
    """T.8 周期限时小测（检索检查点）。items 只存 kc_id/question_id/question_text
    （不含答案——判分时按 question_id 反查 wrong_questions.correct_answer，单一真相源，
    不在这张表复制一份答案增加泄露面）。"""

    __tablename__ = "timed_quizzes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    items: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    time_limit_seconds: Mapped[int] = mapped_column(Integer, server_default="300")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    time_spent_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    score: Mapped[Optional[float]] = mapped_column(Float)
    results: Mapped[Optional[list]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Streak(Base):
    __tablename__ = "streaks"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    current_streak: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    longest_streak: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    last_completed_date: Mapped[Optional[date]] = mapped_column(Date)
    escape_count: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    # 连胜护盾：缺一天且有护盾则自动消耗 1 张保住连胜（Duolingo 式，绑学习过程赚取）
    freezes_available: Mapped[int] = mapped_column(Integer, server_default="2")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== 家长端 =====
class ParentAlert(Base):
    __tablename__ = "parent_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    alert_type: Mapped[Optional[AlertType]] = mapped_column()
    alert_level: Mapped[Optional[AlertLevel]] = mapped_column()
    content: Mapped[Optional[str]] = mapped_column(Text)
    sent_via: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_read: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SpeakingSession(Base):
    __tablename__ = "speaking_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    topic: Mapped[Optional[str]] = mapped_column(String(200))
    turns: Mapped[Optional[dict]] = mapped_column(JSONB)
    pronunciation_scores: Mapped[Optional[dict]] = mapped_column(JSONB)
    overall_progress: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== 教材阅读器 =====


class TextbookFile(Base):
    __tablename__ = "textbook_files"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    textbook_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # FK to textbooks.id (DB-level only)
    owner_student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    has_text_layer: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    file_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("textbook_files.id"), nullable=False
    )
    color: Mapped[str] = mapped_column(
        String(10), server_default="yellow", nullable=False
    )
    highlighted_text: Mapped[str] = mapped_column("text", Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_json: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ReadingNote(Base):
    __tablename__ = "reading_notes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    file_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("textbook_files.id"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlight_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("highlights.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ===== 知识体系 =====


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    subject: Mapped[str] = mapped_column(String(20), nullable=False)
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    edition: Mapped[str] = mapped_column(String(30), nullable=False)
    book_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class KnowledgeCluster(Base):
    __tablename__ = "knowledge_clusters"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    textbook_id: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # FK DB-level only
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_units"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    textbook_id: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # FK DB-level only
    cluster_id: Mapped[str] = mapped_column(
        String(80), nullable=False
    )  # FK DB-level only
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prerequisites: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    # 软前置（建议先学，不阻断）：跟 prerequisites（硬前置，P4 新知识点推荐/fringe
    # 门控靠它判定是否解锁）语义不同、字段独立——不复用 prerequisites 混装类型标签，
    # 避免 daily_plan_service/learner_model/cognitive_service/前端 等既有全部消费者
    # 都要跟着改。默认空表示"无软前置建议"，向后兼容，不影响任何既有掌握度/解锁判定。
    soft_prerequisites: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    related_kus: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    difficulty: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    exam_frequency: Mapped[str] = mapped_column(
        String(10), server_default=text("'mid'")
    )
    question_types: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    ku_type: Mapped[str] = mapped_column(String(20), server_default=text("'concept'"))
    curriculum_standard: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mastery_levels: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    # U.21 骨架（2026-07-04，只搭骨架+小规模试点，未做全量批量标注）：
    # 中高考区域变体标签（如 ["广东","全国甲卷"]）——该 KU 在这些地区考纲/题型上有
    # 显著差异，供考期感知调度（T.7）未来按地区细化用；默认空 = 未标注，非"无差异"。
    exam_region_tags: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    # 教材版本适配层骨架：指向"同一课标条目下的另一版本教材 KU"（如人教版 vs 北师大版
    # 同一知识点），自引用、可空。默认为空 = 未建立跨版本关联（不代表无对应版本）。
    textbook_edition_variant_of: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    rich_content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # 提取可信度（item 2，防 AI 幻觉污染学习）：
    #   provenance     — 溯源元数据 {chunk_id, page_hint, extract_model, extracted_at}
    #   source_excerpt — 该 KU 所依据的**原文片段**（源内容与 AI 内容分离）
    #   ai_generated   — 是否 LLM 生成（默认 True）
    #   verified       — 是否过校验门/人工核验（默认 False，未核验不应被当权威真值）
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    source_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# U.19 英语习得型范式：词汇 FSRS + 分级泛读（i+1）。地基与数学/物理不同——
# 英语当前零 KU/零词汇表/零分级读物，词频/难度分档均从下方同一份 Simple English
# Wikipedia 语料库（CC BY-SA 4.0，见 source_url 溯源）自行统计得出，不依赖许可不明的
# 第三方词表，词汇表与读物同源、同许可。


class VocabularyItem(Base):
    """英语词汇 FSRS 记忆单元。knowledge_point 复用为 f"vocab-{id}"（见 vocab_service）。"""

    __tablename__ = "vocabulary_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    pos: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 词性
    meaning_cn: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    example_sentence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frequency_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # 频率分档 1(最高频)-5(最低频)，由语料库词频分位数切出，供 i+1 读物难度对齐。
    frequency_band: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(50), server_default=text("'simplewiki'"))
    # meaning_cn/example_sentence 是否 LLM 生成（词频/分档本身是确定性统计，不受影响）。
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    
    # SPEC V1
    language: Mapped[str] = mapped_column(String(10), server_default=text("'en'"))
    display_form: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    normalized_form: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lexeme_type: Mapped[str] = mapped_column(String(20), server_default=text("'WORD'"))
    canonical_meaning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phonetic_uk: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phonetic_us: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phonetic_generic: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # CMUdict 原始 ARPAbet（AE1 P AH0 L）。**不要**与上面三列的 IPA 混写——
    # 那三列由教材词表填 IPA，混在一起会让同一批数据出现两套记音体系。存原始
    # 值，IPA/TTS 未来从它派生。见 alembic a7b8c9d0e1f2。
    phonetic_arpabet: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=text("now()")
    )

class VocabularyCollection(Base):
    __tablename__ = "vocabulary_collections"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False) # TEXTBOOK / EXAM
    scope: Mapped[str] = mapped_column(String(20), nullable=False) # K12_SYNC / ZHONGKAO / GAOKAO
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False) # PRIMARY / JUNIOR / SENIOR / UNKNOWN
    grade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    semester: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # 1: 上, 2: 下
    edition: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    curriculum_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    exam_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_relative_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # 来源许可与地址（如 lilinji/English：CC BY-NC-SA 4.0）。见 alembic vlc1a2b3c4d5。
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))

class VocabularyCollectionMembership(Base):
    __tablename__ = "vocabulary_collection_memberships"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(100), ForeignKey("vocabulary_collections.id"), nullable=False)
    vocabulary_item_id: Mapped[str] = mapped_column(String(100), ForeignKey("vocabulary_items.id"), nullable=False)

    source_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_pos: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_phonetic_uk: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_phonetic_us: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_phonetic_generic: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_sentence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source_relative_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_row: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_entry_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))

class VocabularyAffix(Base):
    """词根词缀分解（prefix · root · suffix）。

    独立成表而非加在 vocabulary_items 上：同一词根横跨几十个互不相干的单词，
    「按词根反查同根派生词」是本表的主要用途，独立表才建得起索引。
    展示串（前缀·词根·后缀）由 services.vocab_affixes.format_affix_chain() 生成，
    **不落库** —— 落库就退化成不可查询的拼接串了。
    """

    __tablename__ = "vocabulary_affixes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 每词只存首选分解，避免渲染歧义
    )
    prefix: Mapped[Optional[str]] = mapped_column(String(32))
    # 可空：只被讲清「前缀+后缀」的词（careless = care+less，其 care 被质量门
    # 判为平凡而落空）没有词根位。NOT NULL 会让整批导入原子失败。见 alembic
    # b9c8d7e6f5a4。
    root: Mapped[Optional[str]] = mapped_column(String(48))
    suffix: Mapped[Optional[str]] = mapped_column(String(32))
    meaning_cn: Mapped[Optional[str]] = mapped_column(Text)   # 词根/词缀中文含义，如「说」「能…的」
    origin: Mapped[Optional[str]] = mapped_column(String(120))  # 来源语词，如 拉丁 capere
    # 该分解的可信档位。379 条的权威来源只是散文里的「词根/前缀/后缀」**标注**，
    # 不是历史语言学 —— 散文自身就常把词干/后缀写成「词根」（careless→less、
    # chinese→ese）。展示层必须据此区分「参考表佐证」与「记忆联想」，不得同权呈现。
    # 见 alembic a3b4c5d6e7f8。
    etymology_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'mnemonic_association'")
    )
    source: Mapped[str] = mapped_column(String(32), server_default=text("'WLLM'"))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (
        Index("ix_vocab_affix_root", "root"),
        Index("ix_vocab_affix_suffix", "suffix"),
        Index("ix_vocab_affix_ety_status", "etymology_status"),
    )


class VocabularyXiangxing(Base):
    """象形9000（百词斩）词条。

    音标是**粗 ASCII 转写**（`['erb]`、`[e'bav]`），不是标准 IPA，与已有的
    ARPAbet 不是一回事 —— 展示层不能混用，故独立成表，字段名 ipa_ascii 以示区别。

    释义**不覆盖** vocabulary_items.meaning_cn：象形给的是词典详尽义项，课标给的是
    适合该学段的精简义项，粒度不同而非冲突（与 VocabularyCollocation 同一原则）。

    `ownership_verified` 记录归属是否经例句交叉验证：象形体把形近/音近词分组，
    组头列多个词而其下只有一条详情块，仅凭行相邻会静默错配。判不出即置 false，
    留作人工复核而非静默修补。见 alembic c5d6e7f8a9b0。
    """

    __tablename__ = "vocabulary_xiangxing"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    ipa_ascii: Mapped[Optional[str]] = mapped_column(String(48))
    pos: Mapped[Optional[str]] = mapped_column(String(16))
    meaning_cn: Mapped[str] = mapped_column(Text, nullable=False)
    example_en: Mapped[Optional[str]] = mapped_column(Text)
    example_cn: Mapped[Optional[str]] = mapped_column(Text)
    source_volume: Mapped[str] = mapped_column(String(32), nullable=False)
    ownership_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (
        Index("ix_vocab_xiangxing_item", "vocabulary_item_id"),
        Index("ix_vocab_xiangxing_verified", "ownership_verified"),
    )


class VocabularyCollocation(Base):
    """课标「用法搭配」（短语搭配）。

    独立成表而非加在 vocabulary_items 上：搭配要能反查（「哪些词共享
    `out of breath`」），独立表才建得起索引。

    词义**不在**这里 —— meaning_cn 保持教材词表原文（更完整）；课标给的是适合
    该学段的精简义项，粒度不同而非冲突，不应覆盖。见 alembic c8d9e0f1a2b3。
    """

    __tablename__ = "vocabulary_collocations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    phrase_en: Mapped[str] = mapped_column(Text, nullable=False)
    phrase_cn: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), server_default=text("'CURRICULUM_OCR'"))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (
        UniqueConstraint(
            "vocabulary_item_id", "phrase_en", "phrase_cn", name="uq_vocab_collocation"
        ),
        Index("ix_vocab_collocation_phrase_en", "phrase_en"),
        Index("ix_vocab_collocation_item", "vocabulary_item_id"),
    )


class VocabularyDictionaryGloss(Base):
    """词典来源的中文释义 —— 独立于「教材原文」与「语料派生」两档。

    存在的理由：`vocabulary_derived_glosses` 的 CHECK 约束锁死 `source_kind='corpus_llm'`，
    且其溯源串被硬编码成「从真实语料句派生」。词典来源塞进去那句话就是假的，
    溯源必须是真的。

    **本表没有 frequency 列**：源数据（EchoType `coca20000.json`）实测是**严格字母序**，
    文件名里的 COCA 只说明词表出处，不含 rank。
    """

    __tablename__ = "vocabulary_dictionary_glosses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    gloss: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # 源文件里的行号，用于回溯到具体那一条
    source_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, onupdate=text("now()")
    )


class VocabularyMemoryNode(Base):
    """词汇记忆节点 —— LLM 生成的**联想层**，一词一条。

    本表**只**存生成内容。词源 / 词根 / 搭配 / 释义一律留在各自既有表，渲染时
    读原表，不复制：复制即多一份会漂移的第二来源，且 vocabulary_affixes 已带
    reference_confirmed / mnemonic_association / disputed 三档可信度，扁平字段
    会把「可当词源讲」与「只是记忆联想」抹平。见
    MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §4。

    故本表**没有** etymology / root_logic / collocations 列，也**没有**
    media_reference（2026-10-02 因未成年 + 版权否决）与 image_url（图片 provider
    集成数为 0，存恒 NULL 的 URL 列等于给「图片覆盖率 0%」做假）。见 alembic
    e6f7a8b9c0d2。

    `context_tier` 落**实际取到的层**（1..5），不是最高可用层；tier=5（无真实
    语境）时 `context_absence_reason` 必填（DB CHECK 强制）。`context_evidence`
    存 sentence_id 而非句子文本 —— 句在 timed_sentences，改了不会读到旧句。
    """

    __tablename__ = "vocabulary_memory_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 一词一条，避免渲染歧义（重跑走 upsert）
    )
    # A=有语境+记忆锚点 / B=有语境 / C=无语境。确定性判定，不用 frequency_band
    # （核心范围内该列恒等于 5，无区分度）。
    tier: Mapped[str] = mapped_column(String(1), nullable=False)
    core_image: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_core: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scene: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    family_network: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # 易混词（spec §五 ⚠️易混点 / §九）。存**已可追溯**的那些：门禁
    # CONFUSABLES_GROUNDED 保证给出的都在确定性候选内，这里再过滤一次是为了让
    # verified=False 的现场也干净（门禁不过的行仍会落库供人工复核）。
    # 空列表是合法且常见的结果 —— 判据只有形近，库内无形近词时不该硬凑对照词。
    confusable_words: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    sound_hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    spelling_hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recall_question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(String(100), nullable=False)
    # 只出 prompt，不出 URL：外部图片 provider 集成数为 0。
    image_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    animation_candidate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    animation_scene: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    context_evidence: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    context_absence_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generation_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    generation_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'p0'")
    )
    quality_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (
        Index("ix_vocab_memory_node_item", "vocabulary_item_id"),
        Index("ix_vocab_memory_node_tier", "tier"),
        # 未过质量门的也要能查出来做人工复核/重跑
        Index("ix_vocab_memory_node_unverified", "verified"),
    )


class VocabularyDerivedGloss(Base):
    """从**真实语料句**派生的中文释义（有出处，但不是教材原文）。

    为什么独立成表而不写进 `vocabulary_items.meaning_cn`：那一列承载「教材词表
    原文」的可追溯性。实测 461 个核心单词（有 NCE 真实句）没有中文释义，其中 459 个
    的 `canonical_meaning` 装的是**纯音标**，确定性派生完全走不通。把 LLM 释义写进
    那一列会**一次性丢掉出处信息** —— 这正是词根那侧已经踩过并解决的问题
    （`VocabularyAffix.etymology_status` 专门分三档，而不是把记忆联想塞进释义）。

    `source_sentence_id` 记下「用了哪一句」，释义可回溯到 `timed_sentences` 的具体行。
    `source_kind` 目前只有 `corpus_llm`（DB CHECK 强制）—— 将来若引入别的派生方式
    需要显式放开 CHECK，而不是悄悄复用这一档。

    合规：全局参考数据，非学生 PII（同 vocabulary_items），FK CASCADE → 不进 purge 清单。
    见 alembic d7e8f9a0b1c2。
    """

    __tablename__ = "vocabulary_derived_glosses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("vocabulary_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 一词一条，避免渲染时「两个释义挑哪个」的歧义
    )
    gloss: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'corpus_llm'")
    )
    # 「用了哪一句」——只存 id，句子本身在 timed_sentences（改了不会读到旧句）
    source_sentence_id: Mapped[Optional[str]] = mapped_column(String(100))
    model: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    __table_args__ = (Index("ix_vocab_derived_gloss_item", "vocabulary_item_id"),)


class VocabularyImportBatch(Base):
    __tablename__ = "vocabulary_import_batches"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    files_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_parsed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_failed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    rows_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_valid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_skipped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_invalid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    vocab_created: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vocab_existing: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collections_created: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memberships_created: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memberships_updated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    duplicates_in_collection: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    phrases: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    words: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False) # DRY_RUN / SUCCESS / FAILED / ROLLED_BACK
    report_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


# ===== 通用课程内容链（Course → Book → Lesson → TimedSentence）=====
# 通用教育内容模型：NCE 是 scope=NCE 的第一套完整课程实现；未来 K12 教材
# 词表可投影到同一 Lesson/Sentence 课程链，不写死 NCE only。
class Course(Base):
    """课程（系列）。同一 scope+series 唯一。"""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False) # NCE / K12_SYNC / ...
    series: Mapped[str] = mapped_column(String(50), nullable=False) # NEW_CONCEPT_ENGLISH
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))


class Book(Base):
    """课本。edition 区分版本（current / 1985），不同 edition 是不同课本，绝不混同。

    表名 course_books：public.books 已被教材出版域（textbook compilation）占用，
    本模型是通用课程内容链的一部分，未来 K12 课本也投影到同一张表。
    """

    __tablename__ = "course_books"
    __table_args__ = (
        UniqueConstraint("course_id", "edition", "book_key", name="uq_book_course_edition_key"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(100), ForeignKey("courses.id"), nullable=False)
    book_key: Mapped[str] = mapped_column(String(50), nullable=False) # NCE1..NCE4
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    edition: Mapped[str] = mapped_column(String(50), nullable=False) # CURRENT / 1985
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))


class Lesson(Base):
    """课。lesson_key 在课本内稳定（NCE 用 unit filename 作为 source identity）。"""

    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("book_id", "lesson_key", name="uq_lesson_book_key"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    book_id: Mapped[str] = mapped_column(String(100), ForeignKey("course_books.id"), nullable=False)
    lesson_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    audio_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    audio_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lrc_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    lrc_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))


class TimedSentence(Base):
    """逐句（LRC 行）。end_ms = next.start_ms；末句 end_ms = 真实 audio duration 或 NULL。"""

    __tablename__ = "timed_sentences"
    __table_args__ = (
        UniqueConstraint("lesson_id", "source_entry_key", name="uq_sentence_lesson_entry"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(String(100), ForeignKey("lessons.id"), nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    english_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chinese_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_entry_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))


class LessonVocabularyMembership(Base):
    """课 ↔ canonical VocabularyItem。一个词在一课出现 10 次 = 1 条 membership + occurrence_count=10。"""

    __tablename__ = "lesson_vocabulary_memberships"
    __table_args__ = (
        UniqueConstraint("lesson_id", "vocabulary_item_id", name="uq_lesson_vocab"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(String(100), ForeignKey("lessons.id"), nullable=False)
    vocabulary_item_id: Mapped[str] = mapped_column(String(100), ForeignKey("vocabulary_items.id"), nullable=False)
    first_sentence_id: Mapped[Optional[str]] = mapped_column(String(100), ForeignKey("timed_sentences.id"), nullable=True)
    first_occurrence_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    source_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=text("now()"))


class SentenceVocabularyOccurrence(Base):
    """句 ↔ 词出现记录（token offset 高亮/真实上下文/例句展示用）。"""

    __tablename__ = "sentence_vocabulary_occurrences"
    __table_args__ = (
        UniqueConstraint("sentence_id", "vocabulary_item_id", "occurrence_index", name="uq_sentence_vocab_occurrence"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    sentence_id: Mapped[str] = mapped_column(String(100), ForeignKey("timed_sentences.id"), nullable=False)
    vocabulary_item_id: Mapped[str] = mapped_column(String(100), ForeignKey("vocabulary_items.id"), nullable=False)
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ===== 学习产品层（Textbook-First Learning）=====
# 这些是用户学习产品对象，不是词汇/FSRS authority。
# VocabularyItem 决定词汇身份；KCMastery.fsrs_card_json 决定复习调度；
# 本层只组织"学生今天学什么、学得如何"。
class LearningPlan(Base):
    """用户当前英语学习路线。同一用户只允许一个 ACTIVE English plan。"""

    __tablename__ = "learning_plans"
    __table_args__ = (
        Index(
            "uq_learning_plan_active",
            "user_id",
            "subject",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(20), server_default=text("'english'"))
    primary_scope: Mapped[str] = mapped_column(String(20), server_default=text("'K12_SYNC'"))
    primary_collection_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("vocabulary_collections.id"), nullable=True
    )
    current_book_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("course_books.id"), nullable=True
    )
    current_lesson_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("lessons.id"), nullable=True
    )
    exam_target: Mapped[str] = mapped_column(String(20), server_default=text("'NONE'"))
    nce_support_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    daily_new_word_target: Mapped[int] = mapped_column(
        Integer, server_default=text("10"), nullable=False
    )
    daily_review_target: Mapped[int] = mapped_column(
        Integer, server_default=text("20"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), server_default=text("'ACTIVE'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=text("now()")
    )


class LearningSession(Base):
    """一次真实学习活动。用于学习进度，不是 FSRS authority。"""

    __tablename__ = "learning_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    learning_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_plans.id"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    lesson_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("lessons.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    items_presented: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_correct: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_incorrect: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    new_items: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    review_items: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class LearningSessionItem(Base):
    """Session 内一道题。prompt/context 在 session 开始后不可变（resume 稳定）。"""

    __tablename__ = "learning_session_items"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_session_item_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_sessions.id"), nullable=False
    )
    vocabulary_item_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("vocabulary_items.id"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    context_source: Mapped[str] = mapped_column(String(20), server_default=text("'TEXTBOOK'"))
    sentence_id: Mapped[Optional[str]] = mapped_column(
        String(100), ForeignKey("timed_sentences.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    interaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserLessonProgress(Base):
    """派生状态：一课的进度。可从 LearningEvent + KCMastery 重算。"""

    __tablename__ = "user_lesson_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_user_lesson_progress"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    lesson_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("lessons.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), server_default=text("'not_started'"))
    vocab_total: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    vocab_started: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    vocab_mastered: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lesson_check_score: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserBookProgress(Base):
    """派生状态：一册的进度。课程进度与词汇掌握分开。"""

    __tablename__ = "user_book_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_user_book_progress"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    book_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("course_books.id"), nullable=False
    )
    completed_lessons: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_lessons: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    book_vocab_mastered: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    book_vocab_total: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ReadingPassage(Base):
    """分级泛读文章。difficulty_band 与 VocabularyItem.frequency_band 同一 1-5 分档尺度。"""

    __tablename__ = "reading_passages"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject: Mapped[str] = mapped_column(String(20), server_default=text("'english'"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    license: Mapped[str] = mapped_column(
        String(50), server_default=text("'CC BY-SA 4.0'")
    )
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    readability_score: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_band: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


# ===== Immersive Learning / Media Learning Engine =====
# Python attr is `meta` (not `metadata`) to avoid clobbering DeclarativeBase.metadata.


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # VIDEO|AUDIO
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # USER_UPLOAD|OBJECT_STORAGE
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(16))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # Object key only — never a signed URL.
    storage_ref: Mapped[Optional[str]] = mapped_column(String(500))
    external_ref: Mapped[Optional[str]] = mapped_column(String(500))
    content_provenance: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="USER_UPLOADED"
    )
    processing_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="READY"
    )
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="PRIMARY"
    )  # PRIMARY|TRANSLATION
    source: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # uploaded_subtitle|manual|asr
    format: Mapped[str] = mapped_column(String(16), nullable=False)  # srt|vtt|json
    language: Mapped[Optional[str]] = mapped_column(String(16))
    model_version: Mapped[Optional[str]] = mapped_column(String(120))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    provenance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        CheckConstraint("start_ms >= 0", name="ck_transcript_segments_start_ms"),
        CheckConstraint("end_ms > start_ms", name="ck_transcript_segments_end_ms"),
        UniqueConstraint(
            "transcript_id",
            "order_index",
            name="uq_transcript_segments_transcript_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[Optional[str]] = mapped_column(Text)
    speaker: Mapped[Optional[str]] = mapped_column(String(120))
    language: Mapped[Optional[str]] = mapped_column(String(16))
    confidence: Mapped[Optional[float]] = mapped_column(Float)


class LearningUnit(Base):
    """Stable cross-media learning target (lemma / pattern / concept).

    Identity is ``(kind, stable_key)`` — never a transcript segment id.
    Shared catalog rows have no student_id (not purged per-user).
    """

    __tablename__ = "learning_units"
    __table_args__ = (
        UniqueConstraint("kind", "stable_key", name="uq_learning_units_kind_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False)
    display_text: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(16))
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class LearningUnitOccurrence(Base):
    """Context link: LearningUnit appears in a specific media segment."""

    __tablename__ = "learning_unit_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "learning_unit_id",
            "segment_id",
            name="uq_learning_unit_occurrences_lu_segment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    learning_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("learning_units.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    surface_form: Mapped[Optional[str]] = mapped_column(String(500))
    char_start: Mapped[Optional[int]] = mapped_column(Integer)
    char_end: Mapped[Optional[int]] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MediaSession(Base):
    """Playback continuity only — playhead_ms is not CognitiveState."""

    __tablename__ = "media_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    playhead_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    current_segment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="SET NULL"),
    )
    scaffold_level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="ACTIVE"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class MediaTelemetryEvent(Base):
    """Short-retention player telemetry — NOT learning_events / Evidence."""

    __tablename__ = "media_telemetry_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    media_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# ===== Notebook / Co-Writer（DeepTutor 对标，学习者自有，不进门控）=====


class Notebook(Base):
    """学习者自己的笔记本（命名分组）。只属于 student_id 本人，家长/他人不可读写。

    笔记只是学习者的收藏/整理，永不进 BKT/FSRS/门控判据。
    """

    __tablename__ = "notebooks"
    __table_args__ = (
        UniqueConstraint("student_id", "name", name="uq_notebooks_student_name"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class NotebookRecord(Base):
    """笔记本里的一条记录：来源类型 + 来源 id + kc_id（已知时）+ 内容。

    student_id 冗余存一份（与 notebooks.student_id 一致），用于 owner 过滤与合规清除。
    """

    __tablename__ = "notebook_records"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('chat','book_block','solve','visualize','research',"
            "'cowriter','free_text')",
            name="ck_notebook_records_source_type",
        ),
        Index("ix_notebook_records_notebook_created", "notebook_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    kc_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CowriterRequest(Base):
    """Co-Writer 调用账本：只记字数与结果（不存学生作文原文——数据最小化），
    用于 per-user 每日限额。随用户删除物理清除。"""

    __tablename__ = "cowriter_requests"
    __table_args__ = (
        Index("ix_cowriter_requests_student_created", "student_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

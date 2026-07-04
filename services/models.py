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
    Date,
    DateTime,
    ForeignKey,
    Text,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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


class ErrorType(str, enum.Enum):
    conceptual = "conceptual"
    transfer = "transfer"
    careless = "careless"
    logic_break = "logic_break"
    dontknow = "dontknow"


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


class SocraticMode(str, enum.Enum):
    deep = "deep"
    mixed = "mixed"
    sprint = "sprint"
    force_analysis = "force_analysis"
    reading_guide = "reading_guide"


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
    phone: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(40))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    province: Mapped[Optional[str]] = mapped_column(String(10), server_default="广东")
    exam_date: Mapped[Optional[date]] = mapped_column(Date)  # 考期感知(06)
    share_process_with_parent: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )  # L6 隐私分层
    invite_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True)
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
    guardian_phone: Mapped[str] = mapped_column(String(11), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))


# ===== 学习数据 =====
class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    exam_name: Mapped[Optional[str]] = mapped_column(String(100))
    exam_date: Mapped[Optional[date]] = mapped_column(Date)
    subject: Mapped[Optional[str]] = mapped_column(String(20), server_default="math")
    total_score: Mapped[Optional[int]] = mapped_column(Integer)
    scores: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    exam_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exams.id")
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
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
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


class LearningPattern(Base):
    __tablename__ = "learning_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    pattern_type: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    user_marked_useful: Mapped[Optional[bool]] = mapped_column(Boolean)


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


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("student_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    date: Mapped[Optional[date]] = mapped_column(Date)
    report_text: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[Optional[str]] = mapped_column(String(20))


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

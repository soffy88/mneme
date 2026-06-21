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

class SocraticMode(str, enum.Enum):
    deep = "deep"
    mixed = "mixed"
    sprint = "sprint"

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    phone: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(40))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    province: Mapped[Optional[str]] = mapped_column(String(10), server_default="广东")
    invite_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class ParentStudent(Base):
    __tablename__ = "parent_student"

    parent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(20))
    display_order: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class GuardianConsent(Base):
    __tablename__ = "guardian_consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    guardian_phone: Mapped[str] = mapped_column(String(11), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))


# ===== 学习数据 =====
class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    exam_name: Mapped[Optional[str]] = mapped_column(String(100))
    exam_date: Mapped[Optional[date]] = mapped_column(Date)
    subject: Mapped[Optional[str]] = mapped_column(String(20), server_default="math")
    total_score: Mapped[Optional[int]] = mapped_column(Integer)
    scores: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    exam_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("exams.id"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    subject: Mapped[Optional[str]] = mapped_column(String(20), server_default="math")
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    image_urls: Mapped[Optional[dict]] = mapped_column(JSONB)
    ocr_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    status: Mapped[Optional[PaperStatus]] = mapped_column(server_default=PaperStatus.processing.value)
    storage_tier: Mapped[Optional[StorageTier]] = mapped_column(server_default=StorageTier.hot.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class WrongQuestion(Base):
    __tablename__ = "wrong_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    paper_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("papers.id"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ===== 认知状态（内核落库）=====
class KCMastery(Base):
    __tablename__ = "kc_mastery"
    __table_args__ = (UniqueConstraint("student_id", "knowledge_point"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
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
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    n_attempts: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class BKTPrior(Base):
    __tablename__ = "bkt_priors"
    __table_args__ = (UniqueConstraint("knowledge_point", "question_type", name="uq_bkt_priors_kc_qtype"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    subject: Mapped[Optional[str]] = mapped_column(String(20))
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(100))
    question_type: Mapped[Optional[str]] = mapped_column(String(20))
    p_init: Mapped[Optional[float]] = mapped_column(Float)
    p_transit: Mapped[Optional[float]] = mapped_column(Float)
    p_guess: Mapped[Optional[float]] = mapped_column(Float)
    p_slip: Mapped[Optional[float]] = mapped_column(Float)
    calibrated_from_n: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class InteractionEvent(Base):
    __tablename__ = "interaction_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    knowledge_point: Mapped[str] = mapped_column(String(100), nullable=False)
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source: Mapped[InteractionSource] = mapped_column(nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fsrs_rating: Mapped[Optional[int]] = mapped_column(SmallInteger)
    time_spent_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    days_since_last: Mapped[Optional[float]] = mapped_column(Float)
    is_interleaved: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (UniqueConstraint("student_id", "knowledge_point", "snapshot_month", name="uq_mastery_snapshots_student_kc_month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(100))
    long_term_mastery: Mapped[Optional[float]] = mapped_column(Float)
    dominant_error_type: Mapped[Optional[str]] = mapped_column(String(20))
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    snapshot_month: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class LearningPattern(Base):
    __tablename__ = "learning_patterns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    pattern_type: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    user_marked_useful: Mapped[Optional[bool]] = mapped_column(Boolean)


# ===== 机制增强 =====
class SolveCache(Base):
    __tablename__ = "solve_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kc_id: Mapped[Optional[str]] = mapped_column(String(100))
    problem_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    solve_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    solvable: Mapped[Optional[bool]] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class LessonPage(Base):
    __tablename__ = "lesson_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("wrong_questions.id"))
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    plot_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    diagram_svg: Mapped[Optional[str]] = mapped_column(Text)
    self_check_passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    report_path: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class EffortfulGain(Base):
    __tablename__ = "effortful_gains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    struggle_score: Mapped[Optional[float]] = mapped_column(Float)
    retention_delta: Mapped[Optional[float]] = mapped_column(Float)
    effortful_gain: Mapped[Optional[float]] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ===== 苏格拉底与目标 =====
class SocraticSession(Base):
    __tablename__ = "socratic_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    question_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("wrong_questions.id"))
    mode: Mapped[Optional[SocraticMode]] = mapped_column()
    messages: Mapped[Optional[dict]] = mapped_column(JSONB)
    emotion_log: Mapped[Optional[dict]] = mapped_column(JSONB)
    outcome: Mapped[Optional[SocraticOutcome]] = mapped_column()
    used_escape_hatch: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class DailyMission(Base):
    __tablename__ = "daily_missions"
    __table_args__ = (UniqueConstraint("student_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    date: Mapped[Optional[date]] = mapped_column(Date)
    mission_type: Mapped[Optional[MissionType]] = mapped_column()
    content: Mapped[Optional[dict]] = mapped_column(JSONB)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    interleaved: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    requires_active_recall: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    completed: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class Streak(Base):
    __tablename__ = "streaks"

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    current_streak: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    longest_streak: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    last_completed_date: Mapped[Optional[date]] = mapped_column(Date)
    escape_count: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ===== 家长端 =====
class ParentAlert(Base):
    __tablename__ = "parent_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    alert_type: Mapped[Optional[AlertType]] = mapped_column()
    alert_level: Mapped[Optional[AlertLevel]] = mapped_column()
    content: Mapped[Optional[str]] = mapped_column(Text)
    sent_via: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_read: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("student_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    date: Mapped[Optional[date]] = mapped_column(Date)
    report_text: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[Optional[str]] = mapped_column(String(20))


class SpeakingSession(Base):
    __tablename__ = "speaking_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    topic: Mapped[Optional[str]] = mapped_column(String(200))
    turns: Mapped[Optional[dict]] = mapped_column(JSONB)
    pronunciation_scores: Mapped[Optional[dict]] = mapped_column(JSONB)
    overall_progress: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ===== 教材阅读器 =====

class TextbookFile(Base):
    __tablename__ = "textbook_files"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    textbook_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # FK to textbooks.id (DB-level only)
    owner_student_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(String(50), ForeignKey("textbook_files.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(10), server_default="yellow", nullable=False)
    highlighted_text: Mapped[str] = mapped_column("text", Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class ReadingNote(Base):
    __tablename__ = "reading_notes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_id: Mapped[Optional[str]] = mapped_column(String(50), ForeignKey("textbook_files.id"), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlight_id: Mapped[Optional[str]] = mapped_column(String(50), ForeignKey("highlights.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ===== 知识体系 =====

class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[str]       = mapped_column(String(50),  primary_key=True)
    subject: Mapped[str]  = mapped_column(String(20),  nullable=False)
    grade: Mapped[str]    = mapped_column(String(10),  nullable=False)
    edition: Mapped[str]  = mapped_column(String(30),  nullable=False)
    book_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class KnowledgeCluster(Base):
    __tablename__ = "knowledge_clusters"

    id: Mapped[str]           = mapped_column(String(80),  primary_key=True)
    textbook_id: Mapped[str]  = mapped_column(String(50),  nullable=False)  # FK DB-level only
    name: Mapped[str]         = mapped_column(String(100), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_units"

    id: Mapped[str]             = mapped_column(String(100), primary_key=True)
    textbook_id: Mapped[str]    = mapped_column(String(50),  nullable=False)  # FK DB-level only
    cluster_id: Mapped[str]     = mapped_column(String(80),  nullable=False)  # FK DB-level only
    name: Mapped[str]           = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    prerequisites: Mapped[list]         = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    related_kus: Mapped[list]           = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    difficulty: Mapped[float]           = mapped_column(Float, server_default=text("0.5"))
    exam_frequency: Mapped[str]         = mapped_column(String(10), server_default=text("'mid'"))
    question_types: Mapped[list]        = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    ku_type: Mapped[str]                = mapped_column(String(20), server_default=text("'concept'"))
    curriculum_standard: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mastery_levels: Mapped[list]        = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

"""mneme-core oprim data models — pure value objects, no IO."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class KnowledgeType(str, Enum):
    """Type of knowledge component."""

    MEMORY = "memory"
    PROCEDURE = "procedure"
    CONCEPT = "concept"
    DESIGN = "design"


@dataclass
class KnowledgePoint:
    """A single knowledge component within a module."""

    id: str
    name: str
    type: KnowledgeType
    difficulty: float = (
        0.5  # 0-1；无 IRT 题库参数，退化为 KC 级难度（对齐 KnowledgeUnit.difficulty）
    )


@dataclass
class Module:
    """An ordered collection of knowledge points."""

    id: str
    name: str
    order: int
    knowledge_points: list[KnowledgePoint]


@dataclass
class BktPosterior:
    """Bayesian Knowledge Tracing posterior state for a knowledge point."""

    p_learned: float
    sigma: float  # posterior std dev (for confidence lower bound)
    n_obs: int  # observation count (evidence-insufficient gate)


@dataclass
class FsrsState:
    """Free Spaced Repetition Scheduler state for a knowledge point."""

    stability: float
    difficulty: float
    last_review: float  # unix timestamp
    due_at: float  # unix timestamp
    reps: int


@dataclass
class ReviewTask:
    """A scheduled review task for a knowledge point."""

    knowledge_point_id: str
    due_at: float
    priority: int  # 1=highest (error-linked)


@dataclass
class PendingQuestion:
    """A question awaiting a student's answer."""

    knowledge_point_id: str
    module_id: str
    prompt: str
    expected: str
    qtype: str  # "choice" | "short" | "open"
    question_id: str


@dataclass
class Attempt:
    """A recorded quiz/review attempt."""

    knowledge_point_id: str
    question_id: str
    is_correct: bool
    score: float
    verdict_source: str  # "deterministic" | "llm_verified"
    evidence_ref: Optional[str] = None
    timestamp: float = 0.0


@dataclass
class LearningProgress:
    """Aggregate root — single source of truth for a student's learning state."""

    student_id: str
    modules: list[Module]
    bkt: dict[str, BktPosterior] = field(default_factory=dict)
    qualitative_mastery: dict[str, bool] = field(default_factory=dict)
    fsrs: dict[str, FsrsState] = field(default_factory=dict)
    review_queue: list[ReviewTask] = field(default_factory=list)
    quiz_attempts: list[Attempt] = field(default_factory=list)
    pending_question: Optional[PendingQuestion] = None


class NextAction(str, Enum):
    """Possible next actions for the learning engine to take."""

    ANSWER_PENDING = "answer_pending"
    REVIEW = "review"
    PROBE = "probe"
    PRACTICE = "practice"
    ASSESS = "assess"
    COMPLETE = "complete"


@dataclass(frozen=True)
class NextStep:
    """Immutable value object describing what the student should do next."""

    action: NextAction
    kc_id: Optional[str] = None
    kc_name: Optional[str] = None
    kc_type: Optional[KnowledgeType] = None
    module_id: Optional[str] = None
    pending_question: Optional[PendingQuestion] = None
    review_task: Optional[ReviewTask] = None


# ---------------------------------------------------------------------------
# Qualitative verification I/O schemas (SPEC §1.1 / §3 qualitative_verifier)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RubricDimension:
    """One scoring dimension of a qualitative rubric."""

    name: str
    criterion: str
    weight: float


@dataclass(frozen=True)
class Rubric:
    """A qualitative scoring rubric (mirror of gate.rubric)."""

    kc_id: str
    dimensions: tuple[RubricDimension, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "Rubric":
        """Build from the dict shape gate_store.get_rubric returns."""
        dims = tuple(
            RubricDimension(
                name=str(d["name"]),
                criterion=str(d.get("criterion", "")),
                weight=float(d["weight"]),
            )
            for d in data["dimensions"]
        )
        return cls(kc_id=str(data["kc_id"]), dimensions=dims)


@dataclass(frozen=True)
class KpView:
    """Minimal knowledge-point view handed to the verifier."""

    kc_id: str
    name: str
    gate_type: str  # "qualitative" | "quantitative"


@dataclass(frozen=True)
class EvidenceSpan:
    """A verified citation into the student's explanation.

    ``start``/``end`` index the explanation string; ``quote`` is the exact
    substring ``explanation[start:end]`` (re-verified against hallucination).
    """

    dimension: str
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class DimensionVerdict:
    """Per-dimension outcome after anchoring."""

    name: str
    passed: bool
    spans: tuple[EvidenceSpan, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class QualitativeVerdict:
    """Aggregate verdict of qualitative_verifier."""

    kc_id: str
    passed: bool
    score: float  # weighted sum of passed dimensions' weights, in [0, 1]
    dimensions: tuple[DimensionVerdict, ...]
    evidence_spans: tuple[EvidenceSpan, ...]

    def to_evidence(self) -> dict:
        """Serialise to the dict stored in gate.evidence (for ReportResult)."""
        return {
            "kc_id": self.kc_id,
            "passed": self.passed,
            "score": self.score,
            "dimensions": [
                {
                    "name": d.name,
                    "passed": d.passed,
                    "spans": [
                        {"start": s.start, "end": s.end, "quote": s.quote}
                        for s in d.spans
                    ],
                    "reason": d.reason,
                }
                for d in self.dimensions
            ],
        }

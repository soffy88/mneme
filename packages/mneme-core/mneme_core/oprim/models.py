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


# ── Book Engine (W3 Part B B1) ──────────────────────────────────────────────
#
# DeepTutor（github.com/HKUDS/DeepTutor）book/models.py 面向开放域书籍创作，
# 章节树由 LLM 自由设计。Mneme 面向单本已索引数学教材，章节树扎根于既有
# knowledge_clusters/knowledge_units（真实课程结构，常有重复/无描述文本），
# LLM 的角色是组织/去重/描述这份已有数据，不是从零发明。


class BookContentType(str, Enum):
    """章节内容形态，驱动 page_planner 的块序模板选择。"""

    THEORY = "theory"  # 概念讲解：section + figure + quiz + flash_cards
    PRACTICE = "practice"  # 应用/习题为主：quiz + text(讲解)
    CONCEPT = "concept"  # 定义/术语类：section + flash_cards + quiz


class BookBlockType(str, Enum):
    """页面内容块类型（W3 B2 才实现生成器；B1 只产出块序 shell）。"""

    TEXT = "text"
    CALLOUT = "callout"
    QUIZ = "quiz"
    FIGURE = "figure"
    FLASH_CARDS = "flash_cards"
    GUIDED = "guided"  # 接门控 next_objective（Mneme 特有，DeepTutor 无对应）


@dataclass
class TextbookMeta:
    """喂给 ideation 的教材元信息（真实数据，来自 textbooks 表）。"""

    textbook_id: str
    subject: str
    grade: str
    book_name: str


@dataclass
class ClusterSummary:
    """喂给 ideation/spine 的真实课程结构摘要（来自 knowledge_clusters +
    knowledge_units，非 LLM 输入前先行发明）。ku_names_sample 只取样（≤8 个）
    供 LLM 判断该 cluster 讲的是什么，不是完整清单。
    """

    cluster_id: str
    name: str
    display_order: int
    ku_count: int
    ku_names_sample: list[str] = field(default_factory=list)


@dataclass
class BookProposal:
    """Stage 1（ideation）输出：书的框架描述，供人审阅/编辑。"""

    textbook_id: str
    title: str = ""
    description: str = ""
    scope: str = ""
    target_level: str = ""
    estimated_chapters: int = 0
    rationale: str = ""


@dataclass
class ChapterSpec:
    """Spine 里的一章。cluster_ids 是这章扎根的真实 knowledge_clusters（出处），
    不是 DeepTutor 式自由 source_anchors。
    """

    id: str
    title: str
    content_type: BookContentType = BookContentType.THEORY
    learning_objectives: list[str] = field(default_factory=list)
    cluster_ids: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)  # 其他 chapter id
    summary: str = ""
    order: int = 0


@dataclass
class BookSpine:
    """Stage 2（spine）输出：章节树。"""

    book_id: str
    textbook_id: str
    chapters: list[ChapterSpec] = field(default_factory=list)
    version: int = 1

    def chapter_by_id(self, chapter_id: str) -> Optional["ChapterSpec"]:
        for ch in self.chapters:
            if ch.id == chapter_id:
                return ch
        return None


@dataclass
class BlockSpec:
    """Stage 3（page_planner）输出：一个块的 shell（类型+参数），未生成内容。
    B2 才会把这个 shell 交给对应 block generator 填 payload。
    """

    type: BookBlockType
    params: dict = field(default_factory=dict)


# ── Solve 模式（W4 §2）───────────────────────────────────────────────────────
#
# 单源注册表：7 个确定性求解内核各自支持的真实 task（只列已实现的分支——
# solve_function 的 TaskType Literal 里还声明了 "domain"、solve_geometry3d
# 声明了 "plane_equation"，但两者内核本体都没有实现对应分支，选中会直接报
# "Unknown task"，故不列入，防止 LLM 被引导去选一个必然失败的 task）。
# plan_solve_task（题意理解）与 vendor/oskill/solve_dispatch（实际调度）都读
# 这一份定义，不各自维护一份副本。

SOLVE_KERNEL_TASKS: dict[str, tuple[str, ...]] = {
    "function": (
        "zeros",
        "evaluate",
        "parity",
        "simplify",
        "compose",
        "monotonicity",
        "inverse",
    ),
    "conic": (),  # 无 task 参数，只有 expression
    "derivative": (
        "derivative",
        "critical_points",
        "extrema",
        "inflection",
        "tangent_line",
    ),
    "trig": ("solve", "simplify", "evaluate", "period", "identity"),
    "sequence": ("nth_term", "sum", "type_check"),
    "geometry3d": (
        "distance",
        "midpoint",
        "sphere",
        "cylinder",
        "cone",
        "angle_planes",
    ),
    "probability": (
        "combinations",
        "permutations",
        "basic",
        "conditional",
        "bayes",
        "binomial",
        "expected_value",
    ),
}

SOLVE_KERNEL_PARAM_HINTS: dict[str, str] = {
    "function": (
        "expression(str), variable(str,默认x), point(float,evaluate用), "
        "g_expression(str,compose用)"
    ),
    "conic": "expression(str，如 'x^2+y^2=25' 或 'x**2+y**2=25')",
    "derivative": (
        "expression(str), variable(str,默认x), order(int,默认1), "
        "point(float,tangent_line用)"
    ),
    "trig": (
        "expression(str), variable(str,默认x), angle_degrees(float,evaluate用), "
        "rhs(str,solve用，默认'0')"
    ),
    "sequence": "terms(数字列表，至少2项), n(int,nth_term用), count(int,sum用)",
    "geometry3d": (
        "p1/p2(三元组[x,y,z],distance/midpoint用), "
        "radius/height(float,sphere/cylinder/cone用), "
        "normal1/normal2(三元组[x,y,z],angle_planes用)"
    ),
    "probability": (
        "n/k(int,组合排列/二项分布用), p_a/p_b(float,basic用), "
        "p_a_given_b/p_b_given_a(float,条件概率/贝叶斯用), "
        "p_success(float,二项分布用), values/probabilities(数字列表,期望值用)"
    ),
}


@dataclass
class SolveTaskPlan:
    """plan_solve_task 输出：把自然语言题目映射到确定性内核的调用计划。

    kernel/task 只能是 SOLVE_KERNEL_TASKS 里真实存在的值——校验在
    plan_solve_task 里做，这里只是数据容器。error 非空表示题意理解失败/
    校验不过，调用方不应该拿 kernel/task/params 去调度（大概率是空/无效值）。
    """

    kernel: str = ""
    task: str = ""
    params: dict = field(default_factory=dict)
    restated_problem: str = ""
    error: str = ""
    params: dict = field(default_factory=dict)

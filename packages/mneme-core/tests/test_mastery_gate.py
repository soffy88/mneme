"""Tests for mastery_gate — §10 verification."""

from mneme_core.oprim.mastery_gate import is_mastered, next_objective
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
    NextAction,
    PendingQuestion,
    ReviewTask,
)


def _make_progress(
    kps, bkt=None, qualitative=None, pending=None, review_queue=None, fsrs=None
):
    mod = Module(id="m1", name="Module 1", order=0, knowledge_points=kps)
    return LearningProgress(
        student_id="s1",
        modules=[mod],
        bkt=bkt or {},
        qualitative_mastery=qualitative or {},
        review_queue=review_queue or [],
        fsrs=fsrs or {},
        pending_question=pending,
    )


def test_next_objective_precedence():
    """pending > review > practice > complete."""
    kp = KnowledgePoint(id="k1", name="Test", type=KnowledgeType.MEMORY)
    pending = PendingQuestion(
        knowledge_point_id="k1",
        module_id="m1",
        prompt="?",
        expected="A",
        qtype="choice",
        question_id="q1",
    )
    review = ReviewTask(knowledge_point_id="k1", due_at=0.0, priority=1)

    # With pending
    p = _make_progress([kp], pending=pending)
    step = next_objective(p, now=100.0)
    assert step.action == NextAction.ANSWER_PENDING

    # With review (no pending)
    p = _make_progress([kp], review_queue=[review])
    step = next_objective(p, now=100.0)
    assert step.action == NextAction.REVIEW

    # Unmastered KP (no pending, no review)
    p = _make_progress([kp])
    step = next_objective(p, now=100.0)
    assert step.action == NextAction.PROBE  # new KP = probe


def test_gate_is_cursor():
    """Mastered KPs are skipped by next_objective."""
    k1 = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    k2 = KnowledgePoint(id="k2", name="K2", type=KnowledgeType.MEMORY)

    # k1 mastered (high P(L), low sigma, enough obs)
    bkt = {"k1": BktPosterior(p_learned=0.95, sigma=0.02, n_obs=10)}
    p = _make_progress([k1, k2], bkt=bkt)
    step = next_objective(p, now=100.0)
    assert step.kc_id == "k2"  # k1 skipped


def test_lower_bound_gate():
    """High P(L) but high sigma (small n_obs) → lower bound doesn't pass gate."""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)

    # P(L) = 0.92 but sigma = 0.1 → lower_bound = 0.92 - 0.84*0.1 = 0.836 < 0.9
    bkt = {"k1": BktPosterior(p_learned=0.92, sigma=0.1, n_obs=3)}
    p = _make_progress([kp], bkt=bkt)
    assert not is_mastered(p, kp)


def test_n_min():
    """n_obs < N_MIN → is_mastered=False regardless of P(L)."""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    bkt = {"k1": BktPosterior(p_learned=0.99, sigma=0.01, n_obs=1)}  # n_obs=1 < N_MIN=2
    p = _make_progress([kp], bkt=bkt)
    assert not is_mastered(p, kp)


def test_qualitative_mastery():
    """Concept type uses qualitative_mastery dict."""
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.CONCEPT)
    p = _make_progress([kp], qualitative={"k1": True})
    assert is_mastered(p, kp)
    p2 = _make_progress([kp], qualitative={})
    assert not is_mastered(p2, kp)

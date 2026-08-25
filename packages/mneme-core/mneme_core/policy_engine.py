"""Deterministic unified next-best-action policy.

The policy ranks supplied learning opportunities; it does not infer mastery and
it never writes learner state.  Inputs are explicit so a replay/evaluation run
can reproduce the same decision from the same candidate set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True, slots=True)
class PolicyCandidate:
    candidate_id: str
    action: str
    estimated_minutes: float
    expected_gain: float
    mastery: float = 0.5
    item_difficulty: float = 0.5
    due_urgency: float = 0.0
    transfer_need: float = 0.0
    exam_relevance: float = 0.0
    learner_choice: float = 0.0
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Weights for one policy decision; defaults are intentionally explainable."""

    near_exam: bool = False
    retention_weight: float = 0.35
    transfer_weight: float = 0.20
    exam_weight: float = 0.20
    choice_weight: float = 0.10
    zpd_weight: float = 0.15


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    candidate_id: str | None
    action: str | None
    score: float | None
    objective: str
    reason: str
    considered: int


def score_candidate(
    candidate: PolicyCandidate,
    context: PolicyContext | None = None,
) -> float:
    """Score expected learning gain per minute plus retention/transfer value."""

    context = context or PolicyContext()
    if candidate.blocked or candidate.estimated_minutes <= 0:
        return float("-inf")
    minutes = max(float(candidate.estimated_minutes), 1.0)
    # Dynamic ZPD target: weaker learners benefit from a gentler item, while
    # stronger learners are offered more difficult retrieval opportunities.
    target_difficulty = _clip(0.35 + 0.35 * _clip(candidate.mastery))
    zpd_fit = 1.0 - abs(_clip(candidate.item_difficulty) - target_difficulty)
    new_learning_penalty = 0.0
    if context.near_exam and candidate.action in {"new_learn", "learn_new"}:
        new_learning_penalty = 0.50
    raw = (
        _clip(candidate.expected_gain)
        + context.retention_weight * _clip(candidate.due_urgency)
        + context.transfer_weight * _clip(candidate.transfer_need)
        + context.exam_weight * _clip(candidate.exam_relevance)
        + context.choice_weight * _clip(candidate.learner_choice)
        + context.zpd_weight * _clip(zpd_fit)
        - new_learning_penalty
    )
    return round(raw / minutes, 8)


def rank_candidates(
    candidates: Iterable[PolicyCandidate],
    context: PolicyContext | None = None,
) -> list[tuple[PolicyCandidate, float]]:
    """Return a stable score ordering with candidate ID as the final tie-break."""

    context = context or PolicyContext()
    scored = [(candidate, score_candidate(candidate, context)) for candidate in candidates]
    return sorted(scored, key=lambda item: (-item[1], item[0].candidate_id))


def choose_next_action(
    candidates: Iterable[PolicyCandidate],
    context: PolicyContext | None = None,
) -> PolicyDecision:
    context = context or PolicyContext()
    ranked = [item for item in rank_candidates(candidates, context) if item[1] != float("-inf")]
    if not ranked:
        return PolicyDecision(
            candidate_id=None,
            action=None,
            score=None,
            objective="expected_learning_gain_per_minute",
            reason="没有可执行候选项",
            considered=0,
        )
    candidate, score = ranked[0]
    reasons = ["单位时间预期学习收益最高"]
    if candidate.due_urgency >= 0.7:
        reasons.append("接近遗忘临界")
    if candidate.transfer_need >= 0.7:
        reasons.append("迁移证据不足")
    if context.near_exam and candidate.action in {"review", "error_review", "weak_practice"}:
        reasons.append("临考窗口优先巩固")
    return PolicyDecision(
        candidate_id=candidate.candidate_id,
        action=candidate.action,
        score=score,
        objective="expected_learning_gain_per_minute",
        reason="；".join(reasons),
        considered=len(ranked),
    )

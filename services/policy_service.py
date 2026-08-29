"""Service adapter from persisted learner state to the pure policy engine."""

from __future__ import annotations

import math
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.policy_engine import (
    PolicyCandidate,
    PolicyContext,
    choose_next_action,
    rank_candidates,
)
from services.models import InteractionEvent, InteractionSource, KCMastery
from services.policy_trace import PolicyDecision as PolicyTrace


def _task_signal(task: dict[str, Any], name: str, default: float) -> float:
    value = task.get(name, default)
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _fallback_expected_gain(
    *, mastery: float, item_difficulty: float, due_urgency: float
) -> float:
    """Estimate gain from explicit state signals when a planner omits a score.

    This is a transparent cold-start estimate, not a claim learned from data.
    Once the planner/evaluation pipeline supplies ``expected_learning_gain``,
    that measured value is used verbatim (after policy-engine clipping).
    """

    target = max(0.0, min(1.0, 0.35 + 0.35 * mastery))
    zpd_fit = 1.0 - abs(item_difficulty - target)
    return max(
        0.0,
        min(1.0, 0.55 * (1.0 - mastery) + 0.25 * zpd_fit + 0.20 * due_urgency),
    )


def candidates_from_plan(
    tasks: Iterable[dict[str, Any]],
    *,
    mastery_by_kc: dict[str, float] | None = None,
    transfer_by_kc: dict[str, int] | None = None,
) -> list[PolicyCandidate]:
    mastery_by_kc = mastery_by_kc or {}
    transfer_by_kc = transfer_by_kc or {}
    candidates = []
    for index, task in enumerate(tasks):
        ku_ids = [str(value) for value in task.get("ku_ids", [])]
        mastery_values = [mastery_by_kc.get(ku_id, 0.5) for ku_id in ku_ids]
        mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.5
        transfer_n = sum(transfer_by_kc.get(ku_id, 0) for ku_id in ku_ids)
        item_difficulty = _task_signal(
            task,
            "item_difficulty",
            _task_signal(task, "difficulty", 0.5),
        )
        due_urgency = _task_signal(
            task,
            "due_urgency",
            1.0 if task.get("type") == "review" else 0.0,
        )
        expected_gain = task.get("expected_learning_gain")
        if expected_gain is None:
            expected_gain = _fallback_expected_gain(
                mastery=mastery,
                item_difficulty=item_difficulty,
                due_urgency=due_urgency,
            )
        candidates.append(
            PolicyCandidate(
                candidate_id=f"{task.get('type', 'task')}:{task.get('subject', 'all')}:{index}",
                action=str(task.get("type", "task")),
                estimated_minutes=float(task.get("estimated_minutes", 1) or 1),
                expected_gain=float(expected_gain),
                mastery=mastery,
                item_difficulty=item_difficulty,
                due_urgency=due_urgency,
                transfer_need=_task_signal(
                    task, "transfer_need", 1.0 if not transfer_n else 0.0
                ),
                exam_relevance=_task_signal(task, "exam_relevance", 0.0),
                learner_choice=_task_signal(task, "learner_choice", 0.0),
                evidence_count=(
                    int(task["evidence_count"])
                    if task.get("evidence_count") is not None
                    else None
                ),
                epistemic_uncertainty=(
                    float(task["epistemic_uncertainty"])
                    if task.get("epistemic_uncertainty") is not None
                    else None
                ),
                evidence_sufficiency=(
                    float(task["evidence_sufficiency"])
                    if task.get("evidence_sufficiency") is not None
                    else None
                ),
                evidence_refs=tuple(str(ref) for ref in task.get("evidence_refs", [])),
                state_version=(
                    str(task["state_version"])
                    if task.get("state_version") is not None
                    else None
                ),
            )
        )
    return candidates


def annotate_plan_tasks(
    tasks: list[dict[str, Any]],
    *,
    mastery_by_kc: dict[str, float] | None = None,
    transfer_by_kc: dict[str, int] | None = None,
    near_exam: bool = False,
) -> dict[str, Any]:
    candidates = candidates_from_plan(
        tasks, mastery_by_kc=mastery_by_kc, transfer_by_kc=transfer_by_kc
    )
    context = PolicyContext(near_exam=near_exam)
    ranked = rank_candidates(candidates, context)
    score_by_id = {candidate.candidate_id: score for candidate, score in ranked}
    for candidate, task in zip(candidates, tasks):
        task["policy_score"] = score_by_id[candidate.candidate_id]
        task["policy_objective"] = "expected_learning_gain_per_minute"
    return {
        "objective": "expected_learning_gain_per_minute",
        "candidate_count": len(candidates),
        "ranked_candidate_ids": [candidate.candidate_id for candidate, _ in ranked],
    }


async def next_best_action(
    db: AsyncSession,
    student_id: UUID,
    *,
    now=None,
) -> dict[str, Any]:
    from services.daily_plan_service import build_daily_plan

    plan = await build_daily_plan(db, student_id, now=now)
    masteries = (
        await db.execute(select(KCMastery).where(KCMastery.student_id == student_id))
    ).scalars().all()
    mastery_by_kc = {row.knowledge_point: float(row.p_mastery or 0.0) for row in masteries}
    for task in plan["tasks"]:
        refs = [str(ref) for ref in task.get("ku_ids", [])]
        if not refs:
            continue
        rows = [row for row in masteries if row.knowledge_point in refs]
        counts = [int(row.n_attempts or 0) for row in rows]
        uncertainties = []
        sufficiencies = []
        for row in rows:
            p_value = row.p_mastery
            n_value = int(row.n_attempts or 0)
            if p_value is None or n_value <= 0:
                uncertainties.append(1.0)
                sufficiencies.append(0.0)
                continue
            uncertainties.append(
                math.sqrt(max(0.0, float(p_value) * (1.0 - float(p_value)) / (n_value + 1)))
            )
            sufficiencies.append(min(1.0, n_value / 10.0))
        task.setdefault("evidence_count", sum(counts))
        task.setdefault("epistemic_uncertainty", max(uncertainties, default=1.0))
        task.setdefault("evidence_sufficiency", min(sufficiencies, default=0.0))
        task.setdefault("state_version", "cognitive-state/v2")
    transfer_rows = (
        await db.execute(
            select(InteractionEvent.knowledge_point)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.source == InteractionSource.transfer_probe,
            )
        )
    ).all()
    transfer_by_kc: dict[str, int] = {}
    for (kc_id,) in transfer_rows:
        transfer_by_kc[kc_id] = transfer_by_kc.get(kc_id, 0) + 1
    candidates = candidates_from_plan(
        plan["tasks"],
        mastery_by_kc=mastery_by_kc,
        transfer_by_kc=transfer_by_kc,
    )
    # Immersive Learning candidates (feature-flagged) — no separate recommender.
    from services.feature_flags import immersive_learning_enabled

    if immersive_learning_enabled():
        immersive_tasks = [
            {
                "candidate_id": "VIDEO_SEGMENT_TASK",
                "type": "VIDEO_SEGMENT_TASK",
                "estimated_minutes": 3,
                "expected_gain": 0.35,
                "ku_ids": [],
            },
            {
                "candidate_id": "LISTENING_TASK",
                "type": "LISTENING_TASK",
                "estimated_minutes": 4,
                "expected_gain": 0.4,
                "ku_ids": [],
            },
            {
                "candidate_id": "DICTATION_TASK",
                "type": "DICTATION_TASK",
                "estimated_minutes": 4,
                "expected_gain": 0.45,
                "ku_ids": [],
            },
            {
                "candidate_id": "COMPREHENSION_TASK",
                "type": "COMPREHENSION_TASK",
                "estimated_minutes": 3,
                "expected_gain": 0.4,
                "ku_ids": [],
            },
            {
                "candidate_id": "RECALL_TASK",
                "type": "RECALL_TASK",
                "estimated_minutes": 3,
                "expected_gain": 0.5,
                "ku_ids": [],
            },
            {
                "candidate_id": "TRANSFER_TASK",
                "type": "TRANSFER_TASK",
                "estimated_minutes": 5,
                "expected_gain": 0.55,
                "ku_ids": [],
                "transfer_need": 0.8,
            },
        ]
        candidates.extend(
            candidates_from_plan(
                immersive_tasks,
                mastery_by_kc=mastery_by_kc,
                transfer_by_kc=transfer_by_kc,
            )
        )
    decision = choose_next_action(
        candidates,
        PolicyContext(near_exam=bool(plan.get("near_exam"))),
    )
    trace = PolicyTrace.from_core(
        student_id=student_id,
        candidates=candidates,
        decision=decision,
        timestamp=now,
        constraints={"near_exam": bool(plan.get("near_exam"))},
    )
    return {
        "student_id": str(student_id),
        "policy_version": decision.policy_version,
        "decision": {
            "candidate_id": decision.candidate_id,
            "action": decision.action,
            "score": decision.score,
            "objective": decision.objective,
            "reason": decision.reason,
            "considered": decision.considered,
        },
        "policy_decision": trace.model_dump(mode="json"),
        "plan_date": plan.get("date"),
        "near_exam": plan.get("near_exam", False),
    }

"""mneme-core mastery_gate — gate logic and next-objective resolution.

Pure functions, no IO.  Time is always passed as ``now: float`` (unix ts).
"""
from __future__ import annotations

from mneme_core.oprim.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    NextAction,
    NextStep,
)
from mneme_core.oprim.spacing import due_reviews as _due_reviews

# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------
QUANTITATIVE_GATE: dict[KnowledgeType, float] = {
    KnowledgeType.MEMORY: 0.9,
    KnowledgeType.PROCEDURE: 0.9,
}

QUALITATIVE_TYPES: frozenset[KnowledgeType] = frozenset(
    {KnowledgeType.CONCEPT, KnowledgeType.DESIGN}
)

Z: float = 0.84  # z-score for ~80 % confidence lower bound
N_MIN: int = 2  # minimum observations before quantitative gate can pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_mastered(progress: LearningProgress, kp: KnowledgePoint) -> bool:
    """Return whether *kp* is considered mastered given *progress*.

    For **quantitative** types (MEMORY, PROCEDURE):
        - Must have at least ``N_MIN`` observations.
        - The confidence lower bound ``p_learned - Z * sigma`` must meet
          or exceed the gate threshold.

    For **qualitative** types (CONCEPT, DESIGN):
        - Mastery is stored as a boolean flag in
          ``progress.qualitative_mastery[kp.id]``.
    """
    if kp.type in QUALITATIVE_TYPES:
        return progress.qualitative_mastery.get(kp.id, False)

    # Quantitative path
    threshold = QUANTITATIVE_GATE.get(kp.type)
    if threshold is None:
        return False

    bkt = progress.bkt.get(kp.id)
    if bkt is None:
        return False

    if bkt.n_obs < N_MIN:
        return False

    lower_bound = bkt.p_learned - Z * bkt.sigma
    return lower_bound >= threshold


def next_objective(progress: LearningProgress, *, now: float) -> NextStep:
    """Determine the next learning action with 4-level priority.

    Priority order:
        1. **ANSWER_PENDING** — a question is waiting for the student.
        2. **REVIEW** — overdue spaced-repetition review (by priority asc,
           error-linked first).
        3. **First un-mastered KP** by module order:
           - PROBE  if the KP has no BKT state yet (brand-new).
           - ASSESS if the KP is a qualitative type.
           - PRACTICE otherwise (quantitative, needs more reps).
        4. **COMPLETE** — all KPs mastered, nothing to review.
    """
    # --- Priority 1: pending question ---
    if progress.pending_question is not None:
        pq = progress.pending_question
        # Resolve the KP for metadata
        kp = _find_kp(progress, pq.knowledge_point_id)
        return NextStep(
            action=NextAction.ANSWER_PENDING,
            kc_id=pq.knowledge_point_id,
            kc_name=kp.name if kp else None,
            kc_type=kp.type if kp else None,
            module_id=pq.module_id,
            pending_question=pq,
        )

    # --- Priority 2: due reviews ---
    due = _due_reviews(progress.review_queue, now)
    if due:
        task = due[0]
        kp = _find_kp(progress, task.knowledge_point_id)
        return NextStep(
            action=NextAction.REVIEW,
            kc_id=task.knowledge_point_id,
            kc_name=kp.name if kp else None,
            kc_type=kp.type if kp else None,
            module_id=_find_module_id(progress, task.knowledge_point_id),
            review_task=task,
        )

    # --- Priority 3: first un-mastered KP by module order ---
    for module in sorted(progress.modules, key=lambda m: m.order):
        for kp in module.knowledge_points:
            if not is_mastered(progress, kp):
                action = _classify_action(progress, kp)
                return NextStep(
                    action=action,
                    kc_id=kp.id,
                    kc_name=kp.name,
                    kc_type=kp.type,
                    module_id=module.id,
                )

    # --- Priority 4: all done ---
    return NextStep(action=NextAction.COMPLETE)


def map_summary(progress: LearningProgress, *, now: float) -> dict:
    """Return a plain-dict summary of the student's mastery map.

    Keys:
        ``modules`` — list of module summaries (name, mastered/total counts,
        per-KP detail).
        ``next`` — serialised ``NextStep``.
        ``total_mastered`` / ``total_kps`` — aggregate counts.
    """
    total_mastered = 0
    total_kps = 0
    module_summaries: list[dict] = []

    for module in sorted(progress.modules, key=lambda m: m.order):
        kp_details: list[dict] = []
        mod_mastered = 0
        for kp in module.knowledge_points:
            mastered = is_mastered(progress, kp)
            if mastered:
                mod_mastered += 1
            bkt = progress.bkt.get(kp.id)
            kp_details.append(
                {
                    "id": kp.id,
                    "name": kp.name,
                    "type": kp.type.value,
                    "mastered": mastered,
                    "p_learned": bkt.p_learned if bkt else None,
                    "n_obs": bkt.n_obs if bkt else 0,
                }
            )
        total_mastered += mod_mastered
        total_kps += len(module.knowledge_points)
        module_summaries.append(
            {
                "module_id": module.id,
                "module_name": module.name,
                "mastered": mod_mastered,
                "total": len(module.knowledge_points),
                "knowledge_points": kp_details,
            }
        )

    nxt = next_objective(progress, now=now)

    return {
        "modules": module_summaries,
        "next": {
            "action": nxt.action.value,
            "kc_id": nxt.kc_id,
            "kc_name": nxt.kc_name,
            "kc_type": nxt.kc_type.value if nxt.kc_type else None,
            "module_id": nxt.module_id,
        },
        "total_mastered": total_mastered,
        "total_kps": total_kps,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_kp(
    progress: LearningProgress, kp_id: str
) -> KnowledgePoint | None:
    """Locate a KnowledgePoint by ID across all modules."""
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return kp
    return None


def _find_module_id(
    progress: LearningProgress, kp_id: str
) -> str | None:
    """Return the module ID that contains *kp_id*, or None."""
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return module.id
    return None


def _classify_action(
    progress: LearningProgress, kp: KnowledgePoint
) -> NextAction:
    """Decide whether a non-mastered KP needs PROBE, ASSESS, or PRACTICE."""
    # Brand-new KP — no BKT state at all → probe first
    if kp.id not in progress.bkt:
        return NextAction.PROBE

    # Qualitative types → assess (LLM-verified open question path)
    if kp.type in QUALITATIVE_TYPES:
        return NextAction.ASSESS

    # Quantitative types with existing state → more practice
    return NextAction.PRACTICE

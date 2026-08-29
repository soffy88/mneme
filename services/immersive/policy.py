"""Immersive policy helpers — recommendations only; no mastery writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from mneme_core.policy_engine import (
    PolicyCandidate,
    PolicyContext,
    choose_next_action,
)

from services.immersive.constants import SCAFFOLD_LABELS


@dataclass(frozen=True, slots=True)
class ImmersivePolicyResult:
    decision_id: str
    selected_action: str | None
    scaffold_level: int
    reason_codes: tuple[str, ...]
    reason: str
    candidates: tuple[str, ...]
    explain: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "selected_action": self.selected_action,
            "scaffold_level": self.scaffold_level,
            "reason_codes": list(self.reason_codes),
            "reason": self.reason,
            "candidates": list(self.candidates),
            "explain": self.explain,
        }


def recommend_immersive_next(
    *,
    student_id: UUID,
    current_scaffold: int = 0,
    mastery: float | None = None,
    evidence_count: int = 0,
    due_urgency: float = 0.0,
    transfer_need: float = 0.0,
    recent_override: bool = False,
    epistemic_uncertainty: float | None = None,
) -> ImmersivePolicyResult:
    """Build immersive candidates and rank via mneme-core policy engine."""

    mastery_value = 0.5 if mastery is None else float(mastery)
    # Scaffold recommendation: fade as evidence grows and mastery rises.
    if evidence_count < 2 or mastery_value < 0.35:
        recommended_scaffold = 0
        scaffold_reason = "WHY_SUBTITLE_VISIBLE_LOW_EVIDENCE"
    elif mastery_value < 0.55:
        recommended_scaffold = 1
        scaffold_reason = "WHY_TARGET_SUBTITLE"
    elif mastery_value < 0.7:
        recommended_scaffold = 2
        scaffold_reason = "WHY_KEYWORD_HINTS"
    elif mastery_value < 0.85:
        recommended_scaffold = 3
        scaffold_reason = "WHY_SUBTITLE_HIDDEN"
    else:
        recommended_scaffold = 4 if transfer_need < 0.6 else 5
        scaffold_reason = (
            "WHY_ACTIVE_RECALL" if recommended_scaffold == 4 else "WHY_TRANSFER_NOW"
        )

    if recent_override:
        # Respect recent manual override for recommendation baseline.
        recommended_scaffold = current_scaffold
        scaffold_reason = "WHY_RESPECT_USER_OVERRIDE"

    candidates = [
        PolicyCandidate(
            candidate_id="RECOMMEND_SCAFFOLD_LEVEL",
            action="RECOMMEND_SCAFFOLD_LEVEL",
            estimated_minutes=0.5,
            expected_gain=0.2,
            mastery=mastery_value,
            due_urgency=0.0,
            transfer_need=0.0,
            evidence_count=evidence_count,
            epistemic_uncertainty=epistemic_uncertainty,
            evidence_refs=(f"scaffold:{recommended_scaffold}",),
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="LISTENING_TASK",
            action="RECOMMEND_LISTENING_PRACTICE",
            estimated_minutes=3.0,
            expected_gain=0.45 if recommended_scaffold <= 3 else 0.35,
            mastery=mastery_value,
            item_difficulty=0.45,
            due_urgency=due_urgency,
            evidence_count=evidence_count,
            epistemic_uncertainty=epistemic_uncertainty,
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="DICTATION_TASK",
            action="RECOMMEND_DICTATION",
            estimated_minutes=4.0,
            expected_gain=0.5 if recommended_scaffold >= 2 else 0.3,
            mastery=mastery_value,
            item_difficulty=0.55,
            due_urgency=due_urgency,
            evidence_count=evidence_count,
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="COMPREHENSION_TASK",
            action="RECOMMEND_COMPREHENSION_CHECK",
            estimated_minutes=3.0,
            expected_gain=0.4,
            mastery=mastery_value,
            item_difficulty=0.4,
            evidence_count=evidence_count,
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="RECALL_TASK",
            action="RECOMMEND_RECALL",
            estimated_minutes=3.0,
            expected_gain=0.55 if recommended_scaffold >= 4 else 0.25,
            mastery=mastery_value,
            due_urgency=due_urgency,
            evidence_count=evidence_count,
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="TRANSFER_TASK",
            action="RECOMMEND_TRANSFER",
            estimated_minutes=5.0,
            expected_gain=0.6 if transfer_need >= 0.5 else 0.2,
            mastery=mastery_value,
            transfer_need=max(transfer_need, 0.7 if recommended_scaffold >= 5 else 0.2),
            evidence_count=evidence_count,
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate(
            candidate_id="VIDEO_SEGMENT_TASK",
            action="VIDEO_SEGMENT_TASK",
            estimated_minutes=2.0,
            expected_gain=0.3,
            mastery=mastery_value,
            learner_choice=0.4,
            evidence_count=evidence_count,
            state_version="cognitive-state/v2",
        ),
    ]
    decision = choose_next_action(candidates, PolicyContext())
    reason_codes = tuple(decision.reason_codes) + (scaffold_reason,)
    explain = {
        "WHY_SUBTITLE_HIDDEN": recommended_scaffold >= 3,
        "WHY_DICTATION_NOW": decision.selected_action == "DICTATION_TASK",
        "WHY_REVIEW_SCHEDULED": due_urgency >= 0.7,
        "scaffold_label": SCAFFOLD_LABELS.get(recommended_scaffold),
        "student_id": str(student_id),
        "policy_reason": decision.reason,
    }
    return ImmersivePolicyResult(
        decision_id=str(uuid4()),
        selected_action=decision.selected_action,
        scaffold_level=recommended_scaffold,
        reason_codes=reason_codes,
        reason=decision.reason,
        candidates=decision.candidate_actions,
        explain=explain,
    )

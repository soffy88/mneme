"""PolicyDecision trace and persistence boundary.

Policy consumes Cognitive State; it does not write it.  This module stores only
the decision trace and the evidence references used to make it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from mneme_core.policy_engine import PolicyCandidate, PolicyDecision as CoreDecision
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import PolicyDecisionRecord


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    timestamp: datetime
    candidate_actions: list[dict[str, Any]]
    selected_action: dict[str, Any] | None
    reason_codes: list[str]
    state_version: str
    policy_version: str
    evidence_refs: list[str]
    constraints: dict[str, Any]
    expected_utility: float | None = None
    exploration_flag: bool = False
    fallback_reason: str | None = None
    evidence_level: str = "contract"
    trace_id: str | None = None

    @classmethod
    def from_core(
        cls,
        *,
        student_id: UUID,
        candidates: list[PolicyCandidate],
        decision: CoreDecision,
        state_version: str = "cognitive-state/v2",
        timestamp: datetime | None = None,
        trace_id: str | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> "PolicyDecision":
        selected = None
        if decision.candidate_id is not None:
            selected_candidate = next(
                (candidate for candidate in candidates if candidate.candidate_id == decision.candidate_id),
                None,
            )
            if selected_candidate is not None:
                selected = {
                    "candidate_id": selected_candidate.candidate_id,
                    "action": selected_candidate.action,
                    "estimated_minutes": selected_candidate.estimated_minutes,
                }
        evidence_refs = list(
            dict.fromkeys(
                [
                    *decision.evidence_refs,
                    *(ref for candidate in candidates for ref in candidate.evidence_refs),
                ]
            )
        )
        fallback_reason = decision.fallback_reason
        if not evidence_refs and decision.selected_action is not None:
            fallback_reason = fallback_reason or "evidence_refs_unavailable"
        return cls(
            student_id=student_id,
            timestamp=timestamp or datetime.now(UTC),
            candidate_actions=[
                {
                    "candidate_id": candidate.candidate_id,
                    "action": candidate.action,
                    "estimated_minutes": candidate.estimated_minutes,
                    "evidence_count": candidate.evidence_count,
                    "epistemic_uncertainty": candidate.epistemic_uncertainty,
                    "evidence_sufficiency": candidate.evidence_sufficiency,
                    "evidence_refs": list(candidate.evidence_refs),
                }
                for candidate in candidates
            ],
            selected_action=selected,
            reason_codes=list(decision.reason_codes),
            state_version=decision.state_version or state_version,
            policy_version=decision.policy_version,
            evidence_refs=evidence_refs,
            constraints=constraints or {},
            expected_utility=decision.expected_utility,
            exploration_flag=decision.exploration_flag,
            fallback_reason=fallback_reason,
            trace_id=trace_id,
        )


async def persist_policy_decision(
    db: AsyncSession,
    decision: PolicyDecision,
) -> PolicyDecisionRecord:
    """Append a policy trace; this function has no access to mastery columns."""

    row = PolicyDecisionRecord(
        decision_id=decision.decision_id,
        student_id=decision.student_id,
        timestamp=decision.timestamp,
        candidate_actions=decision.candidate_actions,
        selected_action=decision.selected_action,
        reason_codes=decision.reason_codes,
        state_version=decision.state_version,
        policy_version=decision.policy_version,
        evidence_refs=decision.evidence_refs,
        constraints=decision.constraints,
        expected_utility=decision.expected_utility,
        exploration_flag=decision.exploration_flag,
        fallback_reason=decision.fallback_reason,
        evidence_level=decision.evidence_level,
        trace_id=decision.trace_id,
    )
    db.add(row)
    await db.flush()
    return row


def replay_policy_decision(
    candidates: list[PolicyCandidate],
    context: Any = None,
) -> CoreDecision:
    """Re-run the deterministic core policy without persistence or state writes."""

    from mneme_core.policy_engine import choose_next_action

    return choose_next_action(candidates, context)


__all__ = ["PolicyDecision", "persist_policy_decision", "replay_policy_decision"]

"""Memory Router: eligibility gate between Evidence and FSRS.

Does not compute FSRS intervals. Does not invent mastery. Returns a traced
decision for the cognitive write path to optionally call process_interaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from services.immersive.constants import (
    BEHAVIORAL_ACTIONS,
    EVIDENCE_STRENGTH_NONE,
    EVIDENCE_STRENGTH_PERFORMANCE,
    EVIDENCE_STRENGTH_WEAK_BEHAVIORAL,
    MEMORY_ACTIONS,
    PERFORMANCE_RESULT_ACTIONS,
)


@dataclass(frozen=True, slots=True)
class MemoryRouterDecision:
    action: str
    evidence_strength: str
    knowledge_ref: str | None
    reason_codes: tuple[str, ...]
    advance_fsrs: bool
    create_evidence: bool
    confidence_cap: float | None = None
    trace: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "evidence_strength": self.evidence_strength,
            "knowledge_ref": self.knowledge_ref,
            "reason_codes": list(self.reason_codes),
            "advance_fsrs": self.advance_fsrs,
            "create_evidence": self.create_evidence,
            "confidence_cap": self.confidence_cap,
            "trace": dict(self.trace or {}),
        }


def evidence_strength_for_action(action: str) -> str:
    if action in PERFORMANCE_RESULT_ACTIONS:
        return EVIDENCE_STRENGTH_PERFORMANCE
    if action in BEHAVIORAL_ACTIONS:
        return EVIDENCE_STRENGTH_WEAK_BEHAVIORAL
    return EVIDENCE_STRENGTH_NONE


def knowledge_ref_for_unit(kind: str, stable_key: str) -> str:
    return f"lu-{kind.lower()}-{stable_key}"


def route_memory_action(
    *,
    action: str,
    knowledge_refs: list[str] | None,
    correctness: bool | None,
    existing_mastery: bool,
    confidence: float | None = None,
    explicit_practice: bool = False,
    evaluation_phase: str | None = None,
    event_id: UUID | None = None,
) -> MemoryRouterDecision:
    """Decide whether this immersive event may touch FSRS / evidence."""

    strength = evidence_strength_for_action(action)
    refs = [ref for ref in (knowledge_refs or []) if ref]
    primary = refs[0] if refs else None
    trace = {
        "action": action,
        "strength": strength,
        "explicit_practice": explicit_practice,
        "evaluation_phase": evaluation_phase,
        "event_id": str(event_id) if event_id else None,
        "confidence": confidence,
    }

    # Behavioral signals never advance FSRS.
    if strength == EVIDENCE_STRENGTH_WEAK_BEHAVIORAL:
        # Explicit "Practice this" after lookup can become a candidate, but still
        # requires a later performance result — lookup alone never creates memory.
        if action == "vocab_lookup" and not explicit_practice:
            return MemoryRouterDecision(
                action="NO_MEMORY_ACTION",
                evidence_strength=strength,
                knowledge_ref=primary,
                reason_codes=("lookup_not_performance", "behavioral_only"),
                advance_fsrs=False,
                create_evidence=True,
                confidence_cap=0.4,
                trace=trace,
            )
        return MemoryRouterDecision(
            action="NO_MEMORY_ACTION",
            evidence_strength=strength,
            knowledge_ref=primary,
            reason_codes=("behavioral_signal_does_not_advance_fsrs",),
            advance_fsrs=False,
            create_evidence=True,
            confidence_cap=0.3,
            trace=trace,
        )

    if strength != EVIDENCE_STRENGTH_PERFORMANCE:
        return MemoryRouterDecision(
            action="NO_MEMORY_ACTION",
            evidence_strength=strength,
            knowledge_ref=primary,
            reason_codes=("non_performance_event",),
            advance_fsrs=False,
            create_evidence=False,
            trace=trace,
        )

    if not primary:
        return MemoryRouterDecision(
            action="NO_MEMORY_ACTION",
            evidence_strength=strength,
            knowledge_ref=None,
            reason_codes=("missing_knowledge_ref",),
            advance_fsrs=False,
            create_evidence=True,
            trace=trace,
        )

    if confidence is not None and confidence < 0.5:
        return MemoryRouterDecision(
            action="NO_MEMORY_ACTION",
            evidence_strength=strength,
            knowledge_ref=primary,
            reason_codes=("confidence_below_threshold",),
            advance_fsrs=False,
            create_evidence=True,
            confidence_cap=confidence,
            trace=trace,
        )

    if correctness is None:
        return MemoryRouterDecision(
            action="NO_MEMORY_ACTION",
            evidence_strength=strength,
            knowledge_ref=primary,
            reason_codes=("attempt_without_result",),
            advance_fsrs=False,
            create_evidence=True,
            trace=trace,
        )

    if existing_mastery:
        mem_action = "REVIEW_MEMORY" if evaluation_phase in {
            "delayed_test",
            "delayed_7d",
            "delayed_30d",
            "near_transfer",
            "far_transfer",
        } else "UPDATE_MEMORY"
    else:
        mem_action = "CREATE_MEMORY"

    assert mem_action in MEMORY_ACTIONS
    return MemoryRouterDecision(
        action=mem_action,
        evidence_strength=strength,
        knowledge_ref=primary,
        reason_codes=("video_evidence_advances_fsrs_when_eligible", mem_action.lower()),
        advance_fsrs=True,
        create_evidence=True,
        confidence_cap=confidence,
        trace=trace,
    )

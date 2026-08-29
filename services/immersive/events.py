"""Immersive LearningEvent ingest + evidence + optional FSRS advance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from event_schema import (
    EvaluationPhase,
    EventOutcome,
    EventProvenance,
    ItemFeatures,
    LearningEvent,
    PrivacyClass,
    ProcessSignals,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.evidence_graph import append_event_evidence
from services.immersive.constants import (
    BEHAVIORAL_ACTIONS,
    IMMERSIVE_ACTIONS,
    IMMERSIVE_PRACTICE_SOURCE,
    IMMERSIVE_SOURCE,
    PERFORMANCE_RESULT_ACTIONS,
)
from services.immersive.memory_router import route_memory_action
from services.learning_event_service import (
    LearningEventConflictError,
    LearningEventIngestResult,
    append_learning_event,
)
from services.models import KCMastery


class ImmersiveEventError(ValueError):
    pass


def _privacy_for_action(action: str) -> PrivacyClass:
    if action in {"vocab_lookup", "dictation_result", "dictation_attempt"}:
        return PrivacyClass.P2
    return PrivacyClass.P1


async def ingest_immersive_event(
    db: AsyncSession,
    *,
    student_id: UUID,
    action: str,
    object_type: str,
    object_id: str,
    event_id: UUID | None = None,
    session_id: UUID | None = None,
    knowledge_refs: list[str] | None = None,
    response: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    process_signals: dict[str, Any] | None = None,
    intervention: dict[str, Any] | None = None,
    evaluation_phase: str | None = None,
    item_features: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    trace_id: str | None = None,
    occurred_at: datetime | None = None,
    source: str | None = None,
    explicit_practice: bool = False,
    advance_cognition: bool = True,
) -> dict[str, Any]:
    if action not in IMMERSIVE_ACTIONS:
        raise ImmersiveEventError(f"unsupported immersive action: {action}")

    eid = event_id or uuid4()
    now = occurred_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    outcome_model = None
    correctness: bool | None = None
    if outcome is not None:
        correctness = outcome.get("correctness")
        outcome_model = EventOutcome(
            correctness=correctness,
            partial_credit=outcome.get("partial_credit"),
            verifier=outcome.get("verifier"),
            verifier_version=outcome.get("verifier_version"),
            fsrs_rating=outcome.get("fsrs_rating"),
        )

    features = ItemFeatures(
        difficulty=(item_features or {}).get("difficulty"),
        discrimination=(item_features or {}).get("discrimination"),
        modality=(item_features or {}).get("modality") or "video",
        format=(item_features or {}).get("format"),
    )
    signals = ProcessSignals(**(process_signals or {}))
    prov = EventProvenance(
        adapter="immersive",
        source_system="mneme.immersive",
        provider=(provenance or {}).get("provider"),
        model=(provenance or {}).get("model"),
        model_version=(provenance or {}).get("model_version"),
        verifier=(provenance or {}).get("verifier")
        or (outcome_model.verifier if outcome_model else None),
        kernel="immersive.memory_router/1.0.0",
        confidence=(provenance or {}).get("confidence"),
        metadata={
            **(provenance or {}).get("metadata", {}),
            "immersive_action": action,
        },
    )

    phase: EvaluationPhase | None = None
    if evaluation_phase:
        try:
            phase = EvaluationPhase(evaluation_phase)
        except ValueError as exc:
            raise ImmersiveEventError(f"invalid evaluation_phase: {evaluation_phase}") from exc

    event = LearningEvent(
        event_id=eid,
        actor_id=student_id,
        student_id=student_id,
        session_id=session_id,
        occurred_at=now,
        received_at=datetime.now(UTC),
        source=source
        or (
            IMMERSIVE_PRACTICE_SOURCE
            if action in PERFORMANCE_RESULT_ACTIONS or action.endswith("_attempt")
            else IMMERSIVE_SOURCE
        ),
        action=action,
        object_type=object_type,
        object_id=object_id,
        knowledge_refs=list(knowledge_refs or []),
        item_features=features,
        response=response,
        outcome=outcome_model,
        process_signals=signals,
        intervention=intervention,
        evaluation_phase=phase,
        provenance=prov,
        privacy_class=_privacy_for_action(action),
        trace_id=trace_id,
    )

    try:
        ingest: LearningEventIngestResult = await append_learning_event(db, event)
    except LearningEventConflictError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImmersiveEventError(str(exc)) from exc

    existing_mastery = False
    primary_ref = event.knowledge_refs[0] if event.knowledge_refs else None
    if primary_ref:
        existing_mastery = (
            await db.execute(
                select(KCMastery.id).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point == primary_ref,
                )
            )
        ).scalar_one_or_none() is not None

    decision = route_memory_action(
        action=action,
        knowledge_refs=event.knowledge_refs,
        correctness=correctness,
        existing_mastery=existing_mastery,
        confidence=prov.confidence,
        explicit_practice=explicit_practice,
        evaluation_phase=evaluation_phase,
        event_id=eid,
    )

    evidence_id = None
    if ingest.inserted and decision.create_evidence:
        evidence_id = await append_event_evidence(db, event)

    cognition: dict[str, Any] | None = None
    # Idempotent: only advance cognition on first insert.
    if (
        advance_cognition
        and ingest.inserted
        and decision.advance_fsrs
        and decision.knowledge_ref
        and correctness is not None
    ):
        from services.cognitive_service import process_interaction

        cognition = await process_interaction(
            db,
            student_id=student_id,
            kc_id=decision.knowledge_ref,
            is_correct=bool(correctness),
            event_id=None,  # Do not reuse immersive event_id for legacy interaction
            question_type=f"immersive_{action}",
            source="immersive",  # InteractionSource.immersive (PG enum)
            evaluation_phase=evaluation_phase,
            ai_assisted=(intervention or {}).get("ai_assisted"),
            independent_mode=(intervention or {}).get("independent_mode"),
            time_spent_seconds=signals.time_spent_seconds,
        )

    return {
        "event_id": str(eid),
        "inserted": ingest.inserted,
        "duplicate": ingest.duplicate,
        "action": action,
        "evidence_id": str(evidence_id) if evidence_id else None,
        "memory_router": decision.as_dict(),
        "cognition": cognition,
        "behavioral_only": action in BEHAVIORAL_ACTIONS,
    }

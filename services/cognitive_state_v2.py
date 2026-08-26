"""Versioned, replayable Cognitive State projection.

LearningEvent is the fact boundary.  This module only projects facts and the
authoritative BKT/FSRS kernel output into a typed read model.  It deliberately
returns ``None`` when a dimension has no explicit evidence; a prior or a
heuristic is never presented as observed learner evidence.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from uuid import UUID

from event_schema import (
    EvaluationPhase,
    LearningEvent,
    is_independent_no_ai_event,
    legacy_interaction_to_event,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.evidence_graph import EvidenceClaim, EvidenceRef
from services.models import InteractionEvent, KCMastery, LearningEventRecord


STATE_VERSION = "cognitive-state/v2"
PROJECTION_VERSION = "cognitive-state-projection/1.0.0"
MODEL_VERSION = "bkt-fsrs-recognition/1.0.0"
UNCERTAINTY_RULES_VERSION = "uncertainty-contract/1.0.0"
UNCERTAINTY_RULES: dict[str, float] = {
    "sufficient_events": 10.0,
    "stale_after_days": 30.0,
    "confidence_sigma_multiplier": 2.0,
}


class CognitiveIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    knowledge_ref: str
    state_version: str
    computed_at: datetime
    as_of_event_id: UUID | None = None
    watermark: datetime | None = None
    model_version: str


class KnowledgeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mastery_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    mastery_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_count: int = Field(default=0, ge=0)


class MemoryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrievability: float | None = Field(default=None, ge=0.0, le=1.0)
    stability: float | None = Field(default=None, ge=0.0)
    next_review_at: datetime | None = None
    forgetting_risk: float | None = Field(default=None, ge=0.0, le=1.0)


class RecognitionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recognition_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    recognition_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TransferState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    near_transfer: float | None = Field(default=None, ge=0.0, le=1.0)
    far_transfer: float | None = Field(default=None, ge=0.0, le=1.0)
    transfer_evidence_count: int = Field(default=0, ge=0)


class MisconceptionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_misconceptions: list[str] = Field(default_factory=list)
    misconception_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MetacognitionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jol_calibration: float | None = Field(default=None, ge=0.0, le=1.0)
    self_explanation_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    help_seeking_dependency: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_dependency: float | None = Field(default=None, ge=0.0, le=1.0)


class UncertaintyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epistemic_uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_sufficiency: float | None = Field(default=None, ge=0.0, le=1.0)
    stale: bool | None = None
    out_of_distribution: bool | None = None
    rules_version: str = UNCERTAINTY_RULES_VERSION


class StateProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_event_ids: list[UUID] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    kernel_versions: dict[str, str] = Field(default_factory=dict)
    projection_version: str = PROJECTION_VERSION


class CognitiveStateV2(BaseModel):
    """The single learner-state projection exposed to policy and explanation."""

    model_config = ConfigDict(extra="forbid")

    identity: CognitiveIdentity
    knowledge: KnowledgeState
    memory: MemoryState
    recognition: RecognitionState
    transfer: TransferState
    misconception: MisconceptionState
    metacognition: MetacognitionState
    uncertainty: UncertaintyState
    provenance: StateProvenance
    evidence_claims: list[EvidenceClaim] = Field(default_factory=list)
    input_checksum: str | None = None
    projection_checksum: str | None = None
    trace_id: str | None = None

    _default_kernel_versions: ClassVar[dict[str, str]] = {
        "mastery": "omodul.cognitive/0.1.0",
        "bkt": "vendor.oprim.bkt/current",
        "fsrs": "vendor.oprim.fsrs_engine/current",
        "recognition": "vendor.oprim.recognition_update/current",
    }

    @classmethod
    def from_observations(
        cls,
        *,
        student_id: UUID,
        knowledge_ref: str,
        events: Iterable[Any],
        mastery: Any = None,
        replay_state: Mapping[str, Any] | None = None,
        computed_at: datetime | None = None,
        input_checksum: str | None = None,
        projection_checksum: str | None = None,
    ) -> "CognitiveStateV2":
        event_rows = [
            event
            for event in events
            if knowledge_ref in _knowledge_refs(event)
        ]
        event_rows.sort(key=lambda event: (_occurred_at(event), _event_id(event).hex))
        effective_at = computed_at or (
            _occurred_at(event_rows[-1]) if event_rows else datetime(1970, 1, 1, tzinfo=UTC)
        )
        state_values = _project_values(
            knowledge_ref=knowledge_ref,
            events=event_rows,
            mastery=mastery,
            replay_state=replay_state,
            computed_at=effective_at,
        )
        evidence_refs = [
            _evidence_ref(event, knowledge_ref=knowledge_ref)
            for event in event_rows
        ]
        evidence_refs = list({ref.event_id: ref for ref in evidence_refs}.values())
        evidence_refs.sort(key=lambda ref: (ref.occurred_at, ref.event_id.hex))
        event_ids = [ref.event_id for ref in evidence_refs]
        watermark = evidence_refs[-1].occurred_at if evidence_refs else None
        as_of_event_id = event_ids[-1] if event_ids else None
        identity = CognitiveIdentity(
            student_id=student_id,
            knowledge_ref=knowledge_ref,
            state_version=STATE_VERSION,
            computed_at=effective_at,
            as_of_event_id=as_of_event_id,
            watermark=watermark,
            model_version=MODEL_VERSION,
        )
        provenance = StateProvenance(
            evidence_event_ids=event_ids,
            evidence_refs=evidence_refs,
            kernel_versions=dict(cls._default_kernel_versions),
        )
        claims = _claims(
            state_values,
            knowledge_ref=knowledge_ref,
            evidence_refs=evidence_refs,
            computed_at=effective_at,
        )
        trace_id = next(
            (
                str(_get(event, "trace_id"))
                for event in reversed(event_rows)
                if _get(event, "trace_id")
            ),
            None,
        )
        return cls(
            identity=identity,
            provenance=provenance,
            evidence_claims=claims,
            input_checksum=input_checksum,
            projection_checksum=projection_checksum,
            trace_id=trace_id,
            **state_values,
        )

    @classmethod
    async def rebuild(
        cls,
        db: AsyncSession,
        student_id: UUID,
        knowledge_ref: str,
        as_of: datetime | None = None,
    ) -> "CognitiveStateV2":
        """Rebuild one KC from immutable events using the authoritative kernel."""

        from services.learning_event_replay_service import (
            ReplayConfig,
            replay_events,
        )
        from services.learning_event_service import learning_event_record_to_event

        v2_rows = (
            await db.execute(
                select(LearningEventRecord)
                .where(LearningEventRecord.student_id == student_id)
                .order_by(
                    LearningEventRecord.occurred_at,
                    LearningEventRecord.received_at,
                    LearningEventRecord.event_id,
                )
            )
        ).scalars().all()
        events: list[LearningEvent] = [
            learning_event_record_to_event(row) for row in v2_rows
        ]
        if not events:
            legacy_rows = (
                await db.execute(
                    select(InteractionEvent)
                    .where(InteractionEvent.student_id == student_id)
                    .order_by(InteractionEvent.occurred_at, InteractionEvent.id)
                )
            ).scalars().all()
            events = [legacy_interaction_to_event(row) for row in legacy_rows]
        relevant = [event for event in events if knowledge_ref in event.knowledge_refs]
        effective_at = as_of or (
            max((_occurred_at(event) for event in relevant), default=datetime(1970, 1, 1, tzinfo=UTC))
        )
        projection = await replay_events(
            events,
            student_id=student_id,
            config=ReplayConfig(),
            as_of=as_of,
            computed_at=effective_at,
        )
        mastery = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point == knowledge_ref,
                )
            )
        ).scalar_one_or_none()
        replay_state = projection.states.get(knowledge_ref)
        return cls.from_observations(
            student_id=student_id,
            knowledge_ref=knowledge_ref,
            events=relevant,
            mastery=mastery,
            replay_state=replay_state,
            computed_at=effective_at,
            input_checksum=projection.input_checksum,
            projection_checksum=projection.projection_checksum,
        )

    def compare(self, other: "CognitiveStateV2") -> dict[str, Any]:
        """Compare two versioned projections without treating changes as facts."""

        fields = (
            "knowledge",
            "memory",
            "recognition",
            "transfer",
            "misconception",
            "metacognition",
            "uncertainty",
        )
        changed = [
            field
            for field in fields
            if getattr(self, field) != getattr(other, field)
        ]
        return {
            "same_projection_version": self.provenance.projection_version
            == other.provenance.projection_version,
            "same_model_version": self.identity.model_version == other.identity.model_version,
            "changed_dimensions": changed,
            "left_checksum": self.projection_checksum,
            "right_checksum": other.projection_checksum,
        }


class IndependentMasteryEvidence(BaseModel):
    """A no-AI evidence record safe to use for independent mastery analysis."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    student_id: UUID
    knowledge_ref: str
    evaluation_phase: str = EvaluationPhase.independent_no_ai.value
    occurred_at: datetime
    source: str
    correctness: bool | None
    ai_assisted: bool = False
    independent_mode: bool = True
    evidence_level: str = "contract"


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _nested(value: Any, name: str) -> Any:
    item = _get(value, name)
    if isinstance(item, Mapping):
        return item
    if item is None:
        return {}
    return item.model_dump(mode="json", exclude_none=False)


def _knowledge_refs(event: Any) -> list[str]:
    refs = _get(event, "knowledge_refs")
    if refs:
        return [str(ref) for ref in refs]
    legacy = _get(event, "knowledge_point")
    return [str(legacy)] if legacy is not None else []


def _event_id(event: Any) -> UUID:
    value = _get(event, "event_id", _get(event, "id"))
    return value if isinstance(value, UUID) else UUID(str(value))


def _occurred_at(event: Any) -> datetime:
    value = _get(event, "occurred_at")
    if value is None:
        raise ValueError("learning evidence requires occurred_at")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("learning evidence timestamps must be timezone-aware")
    return value


def _outcome(event: Any) -> bool | None:
    outcome = _get(event, "outcome")
    if isinstance(outcome, Mapping):
        return outcome.get("correctness")
    if outcome is not None:
        return getattr(outcome, "correctness", None)
    return _get(event, "is_correct")


def _phase(event: Any) -> str | None:
    value = _get(event, "evaluation_phase")
    return str(getattr(value, "value", value)) if value is not None else None


def _intervention(event: Any) -> Mapping[str, Any]:
    value = _get(event, "intervention")
    return value if isinstance(value, Mapping) else {}


def _evidence_ref(event: Any, *, knowledge_ref: str) -> EvidenceRef:
    provenance = _nested(event, "provenance")
    outcome = _nested(event, "outcome")
    return EvidenceRef(
        event_id=_event_id(event),
        knowledge_ref=knowledge_ref,
        evidence_type=("transfer" if _phase(event) in {"near_transfer", "far_transfer"} else "learning_event"),
        occurred_at=_occurred_at(event),
        source=str(_get(event, "source", "unknown")),
        weight=1.0,
        confidence=provenance.get("confidence"),
        model_version=provenance.get("model_version"),
        verifier_version=outcome.get("verifier_version"),
        evidence_level="contract",
    )


def _mastery_value(mastery: Any, replay_state: Mapping[str, Any] | None) -> tuple[float | None, int]:
    if replay_state is not None:
        value = replay_state.get("p_mastery")
        return (float(value) if value is not None else None, int(replay_state.get("n_attempts") or 0))
    attempts = int(_get(mastery, "n_attempts", 0) or 0)
    value = _get(mastery, "p_mastery")
    if attempts <= 0 or value is None:
        return None, 0
    return float(value), attempts


def _card_value(mastery: Any, replay_state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if replay_state is not None:
        card = replay_state.get("fsrs_card")
    else:
        card = _get(mastery, "fsrs_card_json")
    return dict(card) if isinstance(card, Mapping) and card else None


def _retrievability(card: Mapping[str, Any] | None, now: datetime) -> float | None:
    if not card:
        return None
    try:
        from oprim.fsrs_engine import fsrs_retrievability

        value = float(fsrs_retrievability(card_dict=dict(card), now=now))
        return round(max(0.0, min(1.0, value)), 6)
    except (KeyError, TypeError, ValueError):
        return None


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo and value.utcoffset() else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo and parsed.utcoffset() else None
    return None


def _project_values(
    *,
    knowledge_ref: str,
    events: list[Any],
    mastery: Any,
    replay_state: Mapping[str, Any] | None,
    computed_at: datetime,
) -> dict[str, Any]:
    p_mastery, attempts = _mastery_value(mastery, replay_state)
    evidence_count = max(len(events), attempts)
    sigma = (
        math.sqrt(max(0.0, p_mastery * (1.0 - p_mastery) / (evidence_count + 1)))
        if p_mastery is not None and evidence_count
        else None
    )
    confidence = (
        max(0.0, min(1.0, 1.0 - UNCERTAINTY_RULES["confidence_sigma_multiplier"] * sigma))
        if sigma is not None
        else None
    )

    card = _card_value(mastery, replay_state)
    retrievability = _retrievability(card, computed_at)
    due = _datetime_value(card.get("due")) if card else None
    stability = None
    if card and card.get("stability") is not None:
        try:
            stability = max(0.0, float(card["stability"]))
        except (TypeError, ValueError):
            stability = None

    recognition = _get(mastery, "p_recognition")
    if replay_state is not None:
        recognition = replay_state.get("p_recognition")
    recognition_probability = float(recognition) if recognition is not None and evidence_count else None
    recognition_confidence = (
        max(0.0, min(1.0, 1.0 - 2.0 * math.sqrt(0.25 / (evidence_count + 1))))
        if recognition_probability is not None
        else None
    )

    transfer_values: dict[str, list[bool]] = {"near_transfer": [], "far_transfer": []}
    jol_pairs: list[tuple[float, bool]] = []
    self_explanation: list[float] = []
    help_dependency: list[float] = []
    answer_dependency: list[float] = []
    misconceptions: list[str] = []
    misconception_confidences: list[float] = []
    for event in events:
        phase = _phase(event)
        result = _outcome(event)
        if phase in transfer_values and result is not None:
            transfer_values[phase].append(bool(result))
        meta = _nested(event, "metacognitive")
        confidence_value = meta.get("jol_confidence", _get(event, "predicted_confidence"))
        if confidence_value is not None and result is not None:
            jol_pairs.append((float(confidence_value), bool(result)))
        for target, destination in (
            ("self_explanation_quality", self_explanation),
            ("help_seeking_dependency", help_dependency),
            ("answer_dependency", answer_dependency),
        ):
            value = meta.get(target)
            if value is not None:
                destination.append(float(value))
        for payload in (_nested(event, "response"), _intervention(event), _nested(event, "provenance")):
            candidate = payload.get("misconception_id", payload.get("misconception"))
            if isinstance(candidate, str) and candidate.strip():
                misconceptions.append(candidate.strip())
                value = payload.get("misconception_confidence")
                if value is not None:
                    misconception_confidences.append(float(value))

    jol_calibration = (
        max(0.0, min(1.0, 1.0 - abs(sum(confidence - float(correct) for confidence, correct in jol_pairs) / len(jol_pairs))))
        if jol_pairs
        else None
    )
    active_misconceptions = list(dict.fromkeys(misconceptions))
    last_event = events[-1] if events else None
    stale = (
        bool(last_event and computed_at - _occurred_at(last_event) > timedelta(days=UNCERTAINTY_RULES["stale_after_days"]))
        if last_event
        else None
    )
    return {
        "knowledge": KnowledgeState(
            mastery_probability=p_mastery,
            mastery_confidence=(round(confidence, 6) if confidence is not None else None),
            evidence_count=evidence_count,
        ),
        "memory": MemoryState(
            retrievability=retrievability,
            stability=(round(stability, 6) if stability is not None else None),
            next_review_at=due,
            forgetting_risk=(round(1.0 - retrievability, 6) if retrievability is not None else None),
        ),
        "recognition": RecognitionState(
            recognition_probability=recognition_probability,
            recognition_confidence=(round(recognition_confidence, 6) if recognition_confidence is not None else None),
        ),
        "transfer": TransferState(
            near_transfer=(round(sum(transfer_values["near_transfer"]) / len(transfer_values["near_transfer"]), 6) if transfer_values["near_transfer"] else None),
            far_transfer=(round(sum(transfer_values["far_transfer"]) / len(transfer_values["far_transfer"]), 6) if transfer_values["far_transfer"] else None),
            transfer_evidence_count=sum(len(values) for values in transfer_values.values()),
        ),
        "misconception": MisconceptionState(
            active_misconceptions=active_misconceptions,
            misconception_confidence=(round(sum(misconception_confidences) / len(misconception_confidences), 6) if misconception_confidences else None),
        ),
        "metacognition": MetacognitionState(
            jol_calibration=(round(jol_calibration, 6) if jol_calibration is not None else None),
            self_explanation_quality=(round(sum(self_explanation) / len(self_explanation), 6) if self_explanation else None),
            help_seeking_dependency=(round(sum(help_dependency) / len(help_dependency), 6) if help_dependency else None),
            answer_dependency=(round(sum(answer_dependency) / len(answer_dependency), 6) if answer_dependency else None),
        ),
        "uncertainty": UncertaintyState(
            epistemic_uncertainty=(round(sigma, 6) if sigma is not None else None),
            evidence_sufficiency=(round(min(1.0, evidence_count / UNCERTAINTY_RULES["sufficient_events"]), 6) if evidence_count else None),
            stale=stale,
            out_of_distribution=None,
        ),
    }


def _claims(
    values: Mapping[str, Any],
    *,
    knowledge_ref: str,
    evidence_refs: list[EvidenceRef],
    computed_at: datetime,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for claim_type, value in (
        ("mastery_probability", values["knowledge"].mastery_probability),
        ("retrievability", values["memory"].retrievability),
        ("near_transfer", values["transfer"].near_transfer),
        ("far_transfer", values["transfer"].far_transfer),
        ("jol_calibration", values["metacognition"].jol_calibration),
    ):
        refs = evidence_refs if value is not None else []
        claims.append(
            EvidenceClaim(
                claim_type=claim_type,
                claim_value=value,
                knowledge_ref=knowledge_ref,
                evidence_refs=refs,
                model_version=MODEL_VERSION,
                computed_at=computed_at,
                uncertainty=values["uncertainty"].model_dump(mode="json"),
                evidence_level="contract",
            )
        )
    return claims


async def get_cognitive_state_with_evidence(
    db: AsyncSession,
    student_id: UUID,
    knowledge_ref: str,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    state = await CognitiveStateV2.rebuild(db, student_id, knowledge_ref, as_of)
    from services.observability import record_cognitive_projection

    record_cognitive_projection(
        evidence_sufficient=state.knowledge.evidence_count > 0
    )
    return state.model_dump(mode="json")


def explain_cognitive_state(state: CognitiveStateV2 | Mapping[str, Any]) -> dict[str, Any]:
    """Return an evidence-indexed explanation; no model or LLM creates claims here."""

    model = state if isinstance(state, CognitiveStateV2) else CognitiveStateV2.model_validate(state)
    return {
        "knowledge_ref": model.identity.knowledge_ref,
        "state_version": model.identity.state_version,
        "model_version": model.identity.model_version,
        "why": [
            {
                "claim_type": claim.claim_type,
                "claim_value": claim.claim_value,
                "uncertainty": claim.uncertainty,
                "evidence_refs": [ref.model_dump(mode="json") for ref in claim.evidence_refs],
                "evidence_level": claim.evidence_level,
            }
            for claim in model.evidence_claims
        ],
    }


async def get_independent_mastery_evidence(
    db: AsyncSession,
    student_id: UUID,
    knowledge_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Return only explicit independent/no-AI events, never inferred ones."""

    rows = (
        await db.execute(
            select(LearningEventRecord)
            .where(LearningEventRecord.student_id == student_id)
            .order_by(LearningEventRecord.occurred_at, LearningEventRecord.event_id)
        )
    ).scalars().all()
    events: list[Any] = []
    if rows:
        from services.learning_event_service import learning_event_record_to_event

        events = [learning_event_record_to_event(row) for row in rows]
    else:
        legacy_rows = (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == student_id)
                .order_by(InteractionEvent.occurred_at, InteractionEvent.id)
            )
        ).scalars().all()
        events = [legacy_interaction_to_event(row) for row in legacy_rows]
    result: list[dict[str, Any]] = []
    for event in events:
        if not is_independent_no_ai_event(event):
            continue
        for ref in _knowledge_refs(event):
            if knowledge_ref is not None and ref != knowledge_ref:
                continue
            item = IndependentMasteryEvidence(
                event_id=_event_id(event),
                student_id=student_id,
                knowledge_ref=ref,
                occurred_at=_occurred_at(event),
                source=str(_get(event, "source", "unknown")),
                correctness=_outcome(event),
            )
            result.append(item.model_dump(mode="json"))
    return result


__all__ = [
    "CognitiveStateV2",
    "EvidenceClaim",
    "EvidenceRef",
    "IndependentMasteryEvidence",
    "get_cognitive_state_with_evidence",
    "get_independent_mastery_evidence",
    "explain_cognitive_state",
    "MODEL_VERSION",
    "PROJECTION_VERSION",
    "STATE_VERSION",
]

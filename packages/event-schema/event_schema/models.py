"""Learning Event v2 contract, legacy adapter and replay ordering.

This module is deliberately persistence-free. It defines the facts that a future
append-only ingest table must accept and the deterministic input boundary that a
projection/replay runner must consume. It does not calculate mastery, write a
database, or decide whether a student is mastered.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrivacyClass(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class EvaluationPhase(str, Enum):
    """Evaluation context used to prevent contaminated mastery evidence."""

    practice = "practice"
    immediate_test = "immediate_test"
    delayed_test = "delayed_test"
    near_transfer = "near_transfer"
    far_transfer = "far_transfer"
    independent_no_ai = "independent_no_ai"
    # Backward-compatible labels used by Evaluation OS v2 before the explicit
    # delayed_test vocabulary was frozen.
    baseline = "baseline"
    delayed = "delayed"


class ItemFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: float | None = Field(default=None, ge=0.0, le=1.0)
    discrimination: float | None = Field(default=None, ge=0.0)
    modality: str | None = None
    format: str | None = None


class EventOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correctness: bool | None = None
    partial_credit: float | None = Field(default=None, ge=0.0, le=1.0)
    verifier: str | None = None
    verifier_version: str | None = None
    fsrs_rating: int | None = Field(default=None, ge=1, le=4)


class ProcessSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ms: int | None = Field(default=None, ge=0)
    time_spent_seconds: int | None = Field(default=None, ge=0)
    attempts: int | None = Field(default=None, ge=0)
    hints: int | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    interruptions: int | None = Field(default=None, ge=0)
    interleaved: bool | None = None
    days_since_last: float | None = Field(default=None, ge=0.0)


class MetacognitiveSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jol_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    self_explanation_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    help_seeking: bool | None = None
    help_seeking_dependency: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_dependency: float | None = Field(default=None, ge=0.0, le=1.0)


class EventProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: str | None = None
    source_system: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    verifier: str | None = None
    kernel: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningEvent(BaseModel):
    """Immutable learning fact at schema version 2.

    ``source`` and ``action`` remain strings rather than closed enums so a new
    product surface can add a value without making old readers unable to parse
    an otherwise valid v2 event. Their vocabulary is governed by the ADR and
    contract tests, while a future incompatible change increments the version.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    schema_version: Literal["2"] = "2"
    actor_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    occurred_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    object_type: str = Field(min_length=1, max_length=64)
    object_id: str = Field(min_length=1, max_length=200)
    content_version: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    item_features: ItemFeatures = Field(default_factory=ItemFeatures)
    response: dict[str, Any] | None = None
    outcome: EventOutcome | None = None
    process_signals: ProcessSignals = Field(default_factory=ProcessSignals)
    metacognitive: MetacognitiveSignals = Field(default_factory=MetacognitiveSignals)
    intervention: dict[str, Any] | None = None
    evaluation_phase: EvaluationPhase | None = None
    provenance: EventProvenance = Field(default_factory=EventProvenance)
    privacy_class: PrivacyClass = PrivacyClass.P1
    trace_id: str | None = None
    supersedes_event_id: uuid.UUID | None = None
    correction_reason: str | None = None

    @field_validator("occurred_at", "received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_correction(self) -> "LearningEvent":
        if self.supersedes_event_id is not None and not self.correction_reason:
            raise ValueError("correction_reason is required for a correction event")
        if self.supersedes_event_id is not None and self.action != "corrected":
            raise ValueError("correction events must use action=corrected")
        if self.action == "corrected" and self.supersedes_event_id is None:
            raise ValueError("corrected events must identify the superseded event")
        if self.evaluation_phase == EvaluationPhase.independent_no_ai:
            intervention = self.intervention or {}
            if intervention.get("ai_assisted") is not False:
                raise ValueError(
                    "independent_no_ai evidence must explicitly set ai_assisted=false"
                )
            if intervention.get("independent_mode") is not True:
                raise ValueError(
                    "independent_no_ai evidence must explicitly set independent_mode=true"
                )
        return self

    @property
    def is_derived_credit(self) -> bool:
        """Whether the event is bookkeeping rather than a student attempt."""

        return self.source == "fire_credit" or self.action == "credited"


def _read_value(record: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TypeError("legacy event timestamp must be ISO-8601") from exc
    if not isinstance(value, datetime):
        raise TypeError("legacy event timestamps must be datetime or ISO-8601 values")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(value)


def legacy_interaction_to_event(
    record: Mapping[str, Any] | object,
) -> LearningEvent:
    """Map a legacy ``InteractionEvent`` row/object to a deterministic v2 event.

    The adapter preserves the legacy ID and occurrence time when present. Missing
    ``received_at`` is set to ``occurred_at`` rather than current time so replaying
    old data does not change its ordering on every run.
    """

    event_id = _as_uuid(_read_value(record, "id")) or uuid.uuid4()
    student_id = _as_uuid(_read_value(record, "student_id"))
    question_id = _as_uuid(_read_value(record, "question_id"))
    knowledge_point = str(_read_value(record, "knowledge_point", "legacy:unknown"))
    occurred_at = _as_datetime(_read_value(record, "occurred_at"))
    if occurred_at is None:
        raise ValueError("legacy InteractionEvent must have occurred_at")
    received_at = _as_datetime(_read_value(record, "received_at")) or occurred_at
    source = str(_enum_value(_read_value(record, "source", "legacy")))
    is_credit = source == "fire_credit"
    self_explanation = _read_value(record, "self_explanation")
    provenance_metadata: dict[str, Any] = {"legacy_id": str(event_id)}
    predicted_r = _read_value(record, "predicted_r")
    if predicted_r is not None:
        provenance_metadata["predicted_r"] = predicted_r

    intervention: dict[str, Any] = {}
    if is_credit:
        intervention = {
            "kind": "fire_credit",
            "metadata": _read_value(record, "fire_meta"),
        }
    for name in ("tutor_mode", "ai_assisted", "independent_mode", "evaluation_phase"):
        value = _read_value(record, name)
        if value is not None:
            intervention[name] = value
    evaluation_phase = _read_value(record, "evaluation_phase")

    return LearningEvent(
        event_id=event_id,
        actor_id=student_id,
        student_id=student_id,
        occurred_at=occurred_at,
        received_at=received_at,
        source=source,
        action="credited" if is_credit else "attempted",
        object_type="question" if question_id else "knowledge_point",
        object_id=str(question_id or knowledge_point),
        knowledge_refs=[knowledge_point],
        response=(
            {"self_explanation": self_explanation}
            if self_explanation is not None
            else None
        ),
        item_features=ItemFeatures(
            difficulty=_read_value(record, "item_difficulty"),
        ),
        outcome=EventOutcome(
            correctness=_as_bool(_read_value(record, "is_correct")),
            fsrs_rating=_read_value(record, "fsrs_rating"),
        ),
        process_signals=ProcessSignals(
            time_spent_seconds=_read_value(record, "time_spent_seconds"),
            days_since_last=_read_value(record, "days_since_last"),
            interleaved=_read_value(record, "is_interleaved"),
        ),
        metacognitive=MetacognitiveSignals(
            jol_confidence=_read_value(record, "predicted_confidence"),
        ),
        intervention=intervention or None,
        evaluation_phase=(
            EvaluationPhase(str(_enum_value(evaluation_phase)))
            if evaluation_phase is not None
            else None
        ),
        provenance=EventProvenance(
            adapter="interaction_event_v1",
            source_system="mneme.services.models.InteractionEvent",
            metadata=provenance_metadata,
        ),
        privacy_class=PrivacyClass.P1,
    )


def is_independent_no_ai_event(event: LearningEvent) -> bool:
    """Return true only for explicitly uncontaminated evaluation evidence."""

    intervention = event.intervention or {}
    return (
        event.evaluation_phase == EvaluationPhase.independent_no_ai
        and bool(intervention)
        and intervention.get("ai_assisted") is False
        and intervention.get("independent_mode") is True
    )


def canonical_replay_events(
    events: Iterable[LearningEvent],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> tuple[LearningEvent, ...]:
    """Filter and deterministically order events for a replay run.

    The end boundary is exclusive. ``as_of`` excludes events whose occurrence or
    receipt is after the replay cutoff, preventing future information leakage.
    """

    for label, boundary in (("start", start), ("end", end), ("as_of", as_of)):
        if boundary is not None and (
            boundary.tzinfo is None or boundary.utcoffset() is None
        ):
            raise ValueError(f"replay {label} must be timezone-aware")

    selected: list[LearningEvent] = []
    for event in events:
        if start is not None and event.occurred_at < start:
            continue
        if end is not None and event.occurred_at >= end:
            continue
        if as_of is not None and (
            event.occurred_at > as_of or event.received_at > as_of
        ):
            continue
        selected.append(event)
    selected.sort(key=lambda item: (item.occurred_at, item.received_at, item.event_id.hex))
    return tuple(selected)


def replay_checksum(events: Iterable[LearningEvent]) -> str:
    """Return a stable checksum for a canonical replay input."""

    canonical = canonical_replay_events(events)
    payload = [event.model_dump(mode="json", exclude_none=False) for event in canonical]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

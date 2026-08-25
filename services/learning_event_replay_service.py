"""Read-only Learning Event v2 replay and projection primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from event_schema import LearningEvent, canonical_replay_events, replay_checksum
from obase.cognitive_store import InMemoryStore
from obase.cognitive_types import fsrs_new_card, new_state_from_prior
from omodul.cognitive import (
    InteractionConfig,
    InteractionInput,
    process_interaction_workflow,
)
from services.learning_event_service import learning_event_record_to_event
from services.models import LearningEventRecord


DEFAULT_REPLAY_PRIOR: dict[str, float] = {
    "p_init": 0.20,
    "p_transit": 0.20,
    "p_guess": 0.15,
    "p_slip": 0.12,
}
REPLAY_STATE_VERSION = "kc_state/v2"
REPLAY_MODEL_VERSION = "omodul.cognitive/0.1.0+oskill.cognitive_state/0.3.0"


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """Explicit replay parameters; changing them changes the projection checksum."""

    model_version: str = REPLAY_MODEL_VERSION
    state_version: str = REPLAY_STATE_VERSION
    min_review_interval_hours: float = 0.0
    fsrs_parameters: tuple[float, ...] | None = None
    fsrs_enable_fuzzing: bool = False
    priors: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


class _ReplayStore(InMemoryStore):
    """In-memory store with explicit priors, isolated from live DB/cache state."""

    def __init__(self, priors: Mapping[str, Mapping[str, float]]):
        super().__init__()
        self._replay_priors = priors

    async def get_or_create(
        self,
        student_id: UUID,
        kc_id: str,
        question_type: str = "solve",
        for_update: bool = False,
    ) -> tuple[Any, dict]:
        key = self._key(student_id, kc_id)
        if key not in self._states:
            prior = dict(self._replay_priors.get(kc_id) or DEFAULT_REPLAY_PRIOR)
            self._states[key] = new_state_from_prior(kc_id=kc_id, prior=prior)
            card = fsrs_new_card()
            # py-fsrs seeds these fields from wall-clock time. A replay must not
            # inherit that operational nondeterminism into its projection hash.
            digest = hashlib.sha256(key.encode("utf-8")).digest()
            card["card_id"] = int.from_bytes(digest[:8], "big")
            card["due"] = "1970-01-01T00:00:00+00:00"
            self._cards[key] = card
        return self._states[key], self._cards[key]


@dataclass(frozen=True, slots=True)
class ReplayProjection:
    student_id: UUID
    state_version: str
    model_version: str
    computed_at: datetime
    input_checksum: str
    projection_checksum: str
    event_count: int
    applied_event_count: int
    evidence_refs: tuple[str, ...]
    skipped_events: tuple[dict[str, str], ...]
    states: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "student_id": str(self.student_id),
            "state_version": self.state_version,
            "model_version": self.model_version,
            "computed_at": self.computed_at.isoformat(),
            "input_checksum": self.input_checksum,
            "projection_checksum": self.projection_checksum,
            "event_count": self.event_count,
            "applied_event_count": self.applied_event_count,
            "evidence_refs": list(self.evidence_refs),
            "skipped_events": list(self.skipped_events),
            "states": self.states,
        }


def _projection_checksum(
    *,
    student_id: UUID,
    state_version: str,
    model_version: str,
    input_checksum: str,
    event_count: int,
    applied_event_count: int,
    evidence_refs: tuple[str, ...],
    skipped_events: tuple[dict[str, str], ...],
    states: dict[str, dict[str, Any]],
) -> str:
    payload = {
        "student_id": str(student_id),
        "state_version": state_version,
        "model_version": model_version,
        "input_checksum": input_checksum,
        "event_count": event_count,
        "applied_event_count": applied_event_count,
        "evidence_refs": list(evidence_refs),
        "skipped_events": list(skipped_events),
        "states": states,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _question_id(event: LearningEvent) -> UUID | None:
    if event.object_type != "question":
        return None
    try:
        return UUID(event.object_id)
    except ValueError:
        return None


def _replay_inputs(event: LearningEvent) -> dict[str, Any] | None:
    if event.action == "corrected":
        return None
    if event.is_derived_credit:
        return None
    if len(event.knowledge_refs) != 1:
        return None
    if event.outcome is None or event.outcome.correctness is None:
        return None

    rating = event.outcome.fsrs_rating
    correct = event.outcome.correctness
    return {
        "ku_id": event.knowledge_refs[0],
        "is_correct": correct,
        "question_id": _question_id(event),
        "source": event.source,
        "is_interleaved": bool(event.process_signals.interleaved),
        "time_spent_seconds": event.process_signals.time_spent_seconds,
        "difficulty": event.item_features.difficulty,
        "predicted_confidence": event.metacognitive.jol_confidence,
        "used_answer": bool(correct and rating == 1),
        "struggled": bool(correct and rating == 2),
        "effortless": bool(correct and rating == 4),
        "now": event.occurred_at,
    }


async def replay_events(
    events: Iterable[LearningEvent],
    *,
    student_id: UUID,
    config: ReplayConfig | None = None,
    as_of: datetime | None = None,
    computed_at: datetime | None = None,
) -> ReplayProjection:
    """Replay one student's canonical events into memory; never writes a DB."""

    replay_config = config or ReplayConfig()
    canonical = canonical_replay_events(events, as_of=as_of)
    input_checksum = replay_checksum(canonical)
    store = _ReplayStore(replay_config.priors)
    workflow_config = InteractionConfig(fire_enabled=False)
    skipped: list[dict[str, str]] = []
    evidence_refs: list[str] = []
    applied = 0
    superseded_ids = {
        event.supersedes_event_id
        for event in canonical
        if event.student_id == student_id
        and event.action == "corrected"
        and event.supersedes_event_id is not None
    }

    for event in canonical:
        if event.student_id != student_id:
            skipped.append({"event_id": str(event.event_id), "reason": "student_mismatch"})
            continue
        if event.event_id in superseded_ids:
            skipped.append(
                {
                    "event_id": str(event.event_id),
                    "reason": "superseded_by_correction",
                }
            )
            continue
        inputs = _replay_inputs(event)
        if inputs is None:
            reason = "correction" if event.action == "corrected" else (
                "derived_credit" if event.is_derived_credit else
                "unsupported_event_shape"
            )
            skipped.append({"event_id": str(event.event_id), "reason": reason})
            continue
        await process_interaction_workflow(
            workflow_config,
            InteractionInput(
                student_id=student_id,
                question_type="solve",
                fsrs_parameters=replay_config.fsrs_parameters,
                min_review_interval_hours=replay_config.min_review_interval_hours,
                fsrs_enable_fuzzing=replay_config.fsrs_enable_fuzzing,
                **inputs,
            ),
            store,
        )
        applied += 1
        evidence_refs.append(str(event.event_id))

    states: dict[str, dict[str, Any]] = {}
    for kc_id, (state, card) in (
        await store.get_all_states(student_id)
    ).items():
        states[kc_id] = {
            "p_mastery": round(state.current(), 8),
            "long_term_mastery": round(state.long_term_mastery or state.current(), 8),
            "p_recognition": (
                round(state.p_recognition, 8)
                if state.p_recognition is not None
                else None
            ),
            "n_attempts": state.n_attempts,
            "last_interaction_at": (
                datetime.fromtimestamp(state.last_interaction_ts, timezone.utc).isoformat()
                if state.last_interaction_ts is not None
                else None
            ),
            "fsrs_card": card,
        }
    skipped_events = tuple(skipped)
    evidence_ref_tuple = tuple(evidence_refs)
    projection_checksum = _projection_checksum(
        student_id=student_id,
        state_version=replay_config.state_version,
        model_version=replay_config.model_version,
        input_checksum=input_checksum,
        event_count=len(canonical),
        applied_event_count=applied,
        evidence_refs=evidence_ref_tuple,
        skipped_events=skipped_events,
        states=states,
    )
    return ReplayProjection(
        student_id=student_id,
        state_version=replay_config.state_version,
        model_version=replay_config.model_version,
        computed_at=computed_at or datetime.now(timezone.utc),
        input_checksum=input_checksum,
        projection_checksum=projection_checksum,
        event_count=len(canonical),
        applied_event_count=applied,
        evidence_refs=evidence_ref_tuple,
        skipped_events=skipped_events,
        states=states,
    )


async def load_student_events(
    db: AsyncSession,
    student_id: UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> tuple[LearningEvent, ...]:
    """Read v2 facts only; SQL filtering is repeated by canonical replay as a guard."""

    stmt = select(LearningEventRecord).where(
        LearningEventRecord.student_id == student_id
    )
    if start is not None:
        stmt = stmt.where(LearningEventRecord.occurred_at >= start)
    if end is not None:
        stmt = stmt.where(LearningEventRecord.occurred_at < end)
    if as_of is not None:
        stmt = stmt.where(
            and_(
                LearningEventRecord.occurred_at <= as_of,
                LearningEventRecord.received_at <= as_of,
            )
        )
    stmt = stmt.order_by(
        LearningEventRecord.occurred_at,
        LearningEventRecord.received_at,
        LearningEventRecord.event_id,
    )
    rows = (await db.execute(stmt)).scalars().all()
    events = tuple(learning_event_record_to_event(row) for row in rows)
    return canonical_replay_events(events, start=start, end=end, as_of=as_of)


async def replay_student_from_db(
    db: AsyncSession,
    student_id: UUID,
    *,
    config: ReplayConfig | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
    computed_at: datetime | None = None,
) -> ReplayProjection:
    events = await load_student_events(
        db,
        student_id,
        start=start,
        end=end,
        as_of=as_of,
    )
    return await replay_events(
        events,
        student_id=student_id,
        config=config,
        as_of=as_of,
        computed_at=computed_at,
    )

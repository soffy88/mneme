"""Persistence boundary for Learning Event v2.

This module only validates/persists immutable facts. It does not update mastery,
run a replay, or decide whether a learner is mastered. Callers own the transaction
and must perform authorization at the HTTP/MCP boundary before invoking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from event_schema import LearningEvent, legacy_interaction_to_event, replay_checksum
from services.models import LearningEventRecord


class LearningEventConflictError(RuntimeError):
    """Raised when an event ID is reused for a different immutable payload."""


@dataclass(frozen=True, slots=True)
class LearningEventIngestResult:
    event_id: UUID
    checksum: str
    inserted: bool

    @property
    def duplicate(self) -> bool:
        return not self.inserted


def _event_record_values(event: LearningEvent) -> dict[str, Any]:
    """Convert the v2 contract into database columns without adding projections."""

    payload = event.model_dump(mode="json", exclude_none=False)
    return {
        "event_id": event.event_id,
        "schema_version": event.schema_version,
        "actor_id": event.actor_id,
        "student_id": event.student_id,
        "session_id": event.session_id,
        "occurred_at": event.occurred_at,
        "received_at": event.received_at,
        "source": event.source,
        "action": event.action,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "content_version": event.content_version,
        "knowledge_refs": payload["knowledge_refs"],
        "item_features": payload["item_features"],
        "response": payload["response"],
        "outcome": payload["outcome"],
        "process_signals": payload["process_signals"],
        "metacognitive": payload["metacognitive"],
        "intervention": payload["intervention"],
        "evaluation_phase": (
            event.evaluation_phase.value if event.evaluation_phase is not None else None
        ),
        "provenance": payload["provenance"],
        "privacy_class": event.privacy_class.value,
        "trace_id": event.trace_id,
        "supersedes_event_id": event.supersedes_event_id,
        "correction_reason": event.correction_reason,
        "event_checksum": replay_checksum((event,)),
    }


def _event_insert_statement(event: LearningEvent):
    values = _event_record_values(event)
    return (
        pg_insert(LearningEventRecord)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[LearningEventRecord.event_id])
        .returning(LearningEventRecord.event_id)
    )


async def append_learning_event(
    db: AsyncSession, event: LearningEvent
) -> LearningEventIngestResult:
    """Append one v2 fact idempotently; caller commits or rolls back the transaction."""

    checksum = replay_checksum((event,))
    from services.observability import record_learning_event_ingest

    record_learning_event_ingest(
        projection_lag_ms=max(
            0,
            int((event.received_at - event.occurred_at).total_seconds() * 1000),
        )
    )
    result = await db.execute(_event_insert_statement(event))
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        return LearningEventIngestResult(
            event_id=event.event_id,
            checksum=checksum,
            inserted=True,
        )

    existing_checksum = (
        await db.execute(
            select(LearningEventRecord.event_checksum).where(
                LearningEventRecord.event_id == event.event_id
            )
        )
    ).scalar_one_or_none()
    if existing_checksum is None:
        # A concurrent transaction should be visible after ON CONFLICT resolves;
        # fail closed if the database cannot provide the idempotency record.
        raise RuntimeError("learning event conflict row disappeared")
    if existing_checksum != checksum:
        raise LearningEventConflictError(
            f"event_id {event.event_id} already exists with a different payload"
        )
    return LearningEventIngestResult(
        event_id=event.event_id,
        checksum=checksum,
        inserted=False,
    )


async def append_legacy_interaction_as_v2(
    db: AsyncSession,
    *,
    event_id: UUID,
    student_id: UUID,
    knowledge_point: str,
    event_data: Mapping[str, Any],
) -> LearningEventIngestResult:
    """Dual-write one already-inserted legacy event using the same event ID."""

    legacy_record = dict(event_data)
    legacy_record.update(
        {
            "id": event_id,
            "student_id": student_id,
            "knowledge_point": knowledge_point,
        }
    )
    event = legacy_interaction_to_event(legacy_record)
    return await append_learning_event(db, event)


def learning_event_record_to_event(
    record: Mapping[str, Any] | object,
) -> LearningEvent:
    """Rehydrate a database row for canonical replay without adding projections."""

    def value(name: str) -> Any:
        if isinstance(record, Mapping):
            return record.get(name)
        return getattr(record, name, None)

    return LearningEvent.model_validate(
        {
            "event_id": value("event_id"),
            "schema_version": value("schema_version"),
            "actor_id": value("actor_id"),
            "student_id": value("student_id"),
            "session_id": value("session_id"),
            "occurred_at": value("occurred_at"),
            "received_at": value("received_at"),
            "source": value("source"),
            "action": value("action"),
            "object_type": value("object_type"),
            "object_id": value("object_id"),
            "content_version": value("content_version"),
            "knowledge_refs": value("knowledge_refs"),
            "item_features": value("item_features"),
            "response": value("response"),
            "outcome": value("outcome"),
            "process_signals": value("process_signals"),
            "metacognitive": value("metacognitive"),
            "intervention": value("intervention"),
            "evaluation_phase": value("evaluation_phase"),
            "provenance": value("provenance"),
            "privacy_class": value("privacy_class"),
            "trace_id": value("trace_id"),
            "supersedes_event_id": value("supersedes_event_id"),
            "correction_reason": value("correction_reason"),
        }
    )

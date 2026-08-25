"""Evidence Graph persistence and redaction helpers.

The graph is deliberately a projection around immutable Learning Event facts.
It can explain a claim, but it cannot create or mutate ``kc_mastery`` and it is
not consulted by the SubmitAnswer mastery path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from event_schema import LearningEvent
from services.models import MemoryClaim, MemoryClaimEvidence, MemoryEvidence


async def append_event_evidence(
    db: AsyncSession,
    event: LearningEvent,
) -> UUID:
    """Create one idempotent evidence node for a v2 event."""

    existing = (
        await db.execute(
            select(MemoryEvidence.id).where(
                MemoryEvidence.student_id == event.student_id,
                MemoryEvidence.source_event_id == event.event_id,
                MemoryEvidence.evidence_type == "learning_event_v2",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if event.student_id is None:
        raise ValueError("student_id is required for student evidence")

    evidence = MemoryEvidence(
        student_id=event.student_id,
        source_event_id=event.event_id,
        evidence_type="learning_event_v2",
        occurred_at=event.occurred_at,
        payload=event.model_dump(mode="json", exclude_none=False),
        provenance={"source": "LearningEvent", "event_checksum": "immutable"},
        privacy_class=event.privacy_class.value,
    )
    db.add(evidence)
    await db.flush()
    return evidence.id


async def create_memory_claim(
    db: AsyncSession,
    *,
    student_id: UUID,
    claim_type: str,
    subject_type: str,
    subject_id: str,
    claim_text: str,
    evidence_ids: list[UUID],
    confidence: float | None = None,
    model_version: str | None = None,
    privacy_class: str = "P1",
    provenance: dict[str, Any] | None = None,
) -> UUID:
    """Create a claim only when it has same-student evidence attached.

    This function is intended for trusted projection jobs.  The public API is
    read-only for claims so an arbitrary client cannot manufacture a narrative.
    """

    if not evidence_ids:
        raise ValueError("a memory claim requires at least one evidence row")
    evidence_rows = (
        await db.execute(
            select(MemoryEvidence).where(
                MemoryEvidence.id.in_(evidence_ids),
                MemoryEvidence.student_id == student_id,
            )
        )
    ).scalars().all()
    if len(evidence_rows) != len(set(evidence_ids)):
        raise ValueError("claim evidence must belong to the same student")
    if not 0.0 <= (confidence if confidence is not None else 0.0) <= 1.0:
        raise ValueError("confidence must be in [0, 1]")

    claim = MemoryClaim(
        student_id=student_id,
        claim_type=claim_type,
        subject_type=subject_type,
        subject_id=subject_id,
        claim_text=claim_text,
        confidence=confidence,
        model_version=model_version,
        privacy_class=privacy_class,
        provenance=provenance or {},
    )
    db.add(claim)
    await db.flush()
    for evidence_id in dict.fromkeys(evidence_ids):
        db.add(
            MemoryClaimEvidence(
                claim_id=claim.id,
                evidence_id=evidence_id,
                relation="supports",
            )
        )
    await db.flush()
    return claim.id


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def claim_evidence_payload(
    claim: MemoryClaim,
    evidence: list[tuple[MemoryClaimEvidence, MemoryEvidence]],
) -> dict[str, Any]:
    return {
        "claim": {
            "id": str(claim.id),
            "student_id": str(claim.student_id),
            "claim_type": claim.claim_type,
            "subject_type": claim.subject_type,
            "subject_id": claim.subject_id,
            "claim_text": claim.claim_text,
            "confidence": claim.confidence,
            "model_version": claim.model_version,
            "privacy_class": claim.privacy_class,
            "provenance": claim.provenance,
            "created_at": _iso(claim.created_at),
        },
        "evidence": [
            {
                "id": str(row.id),
                "relation": edge.relation,
                "source_event_id": (
                    str(row.source_event_id) if row.source_event_id else None
                ),
                "evidence_type": row.evidence_type,
                "occurred_at": _iso(row.occurred_at),
                "payload": row.payload,
                "provenance": row.provenance,
                "privacy_class": row.privacy_class,
            }
            for edge, row in evidence
        ],
    }


def redact_event_for_parent(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove process-level child data when the learner has not shared it."""

    redacted = dict(payload)
    for field in ("response", "process_signals", "metacognitive", "intervention"):
        redacted[field] = None if field in ("response", "intervention") else {}
    redacted["redacted_fields"] = [
        "response",
        "process_signals",
        "metacognitive",
        "intervention",
    ]
    return redacted


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

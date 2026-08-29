"""Listening / dictation / comprehension / recall practice flows."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.immersive.events import ingest_immersive_event
from services.immersive.learning_units import ensure_units_for_segment
from services.immersive.media_service import MediaServiceError, get_owned_media
from services.immersive.memory_router import knowledge_ref_for_unit
from services.immersive.scoring import (
    score_comprehension_choice,
    score_dictation,
    score_listening_meaning,
)
from services.models import LearningUnitOccurrence, TranscriptSegment


async def _segment_for_student(
    db: AsyncSession, *, student_id: UUID, media_id: UUID, segment_id: UUID
) -> TranscriptSegment:
    await get_owned_media(db, student_id=student_id, media_id=media_id)
    seg = (
        await db.execute(
            select(TranscriptSegment).where(TranscriptSegment.id == segment_id)
        )
    ).scalar_one_or_none()
    if seg is None:
        raise MediaServiceError("segment not found", status_code=404)
    return seg


async def _knowledge_refs_for_segment(
    db: AsyncSession, *, media_id: UUID, segment_id: UUID, text: str
) -> list[str]:
    rows = (
        await db.execute(
            select(LearningUnitOccurrence).where(
                LearningUnitOccurrence.segment_id == segment_id
            )
        )
    ).scalars().all()
    if not rows:
        created = await ensure_units_for_segment(
            db, media_id=media_id, segment_id=segment_id, text=text
        )
        return [item["knowledge_ref"] for item in created]
    from services.models import LearningUnit

    refs: list[str] = []
    for occ in rows:
        unit = (
            await db.execute(
                select(LearningUnit).where(LearningUnit.id == occ.learning_unit_id)
            )
        ).scalar_one()
        refs.append(knowledge_ref_for_unit(unit.kind, unit.stable_key))
    return refs


async def run_dictation(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    segment_id: UUID,
    submitted: str,
    session_id: UUID | None = None,
    scaffold_level: int = 3,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    seg = await _segment_for_student(
        db, student_id=student_id, media_id=media_id, segment_id=segment_id
    )
    refs = await _knowledge_refs_for_segment(
        db, media_id=media_id, segment_id=segment_id, text=seg.text
    )
    attempt_id = event_id or uuid4()
    await ingest_immersive_event(
        db,
        student_id=student_id,
        action="dictation_attempt",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=uuid4(),
        session_id=session_id,
        knowledge_refs=refs,
        response={"submitted": submitted},
        intervention={"scaffold_level": scaffold_level},
        item_features={"modality": "audio", "format": "dictation"},
        advance_cognition=False,
    )
    score = score_dictation(seg.text, submitted)
    result = await ingest_immersive_event(
        db,
        student_id=student_id,
        action="dictation_result",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=attempt_id,
        session_id=session_id,
        knowledge_refs=refs[:1] or refs,
        response={
            "submitted": submitted,
            "normalized_submitted": score.normalized_submitted,
            "normalized_expected": score.normalized_expected,
            "edit_distance": score.edit_distance,
        },
        outcome={
            "correctness": score.correctness,
            "partial_credit": score.partial_credit,
            "verifier": score.verifier,
            "verifier_version": score.verifier_version,
        },
        intervention={"scaffold_level": scaffold_level, "ai_assisted": False},
        evaluation_phase="practice",
        item_features={"modality": "audio", "format": "dictation"},
        provenance={"verifier": score.verifier, "confidence": 0.9},
    )
    return {"score": asdict(score), "ingest": result, "segment_text": seg.text}


async def run_listening(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    segment_id: UUID,
    submitted_meaning: str,
    session_id: UUID | None = None,
    scaffold_level: int = 3,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    seg = await _segment_for_student(
        db, student_id=student_id, media_id=media_id, segment_id=segment_id
    )
    refs = await _knowledge_refs_for_segment(
        db, media_id=media_id, segment_id=segment_id, text=seg.text
    )
    expected = seg.translated_text or seg.text
    score = score_listening_meaning(expected, submitted_meaning)
    attempt_id = event_id or uuid4()
    await ingest_immersive_event(
        db,
        student_id=student_id,
        action="listening_attempt",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=uuid4(),
        session_id=session_id,
        knowledge_refs=refs,
        response={"submitted_meaning": submitted_meaning},
        intervention={"scaffold_level": scaffold_level},
        item_features={"modality": "audio", "format": "listening"},
        advance_cognition=False,
    )
    result = await ingest_immersive_event(
        db,
        student_id=student_id,
        action="listening_result",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=attempt_id,
        session_id=session_id,
        knowledge_refs=refs[:1] or refs,
        response={"submitted_meaning": submitted_meaning},
        outcome={
            "correctness": score.correctness,
            "partial_credit": score.partial_credit,
            "verifier": score.verifier,
            "verifier_version": score.verifier_version,
        },
        intervention={"scaffold_level": scaffold_level, "ai_assisted": False},
        evaluation_phase="practice",
        item_features={"modality": "audio", "format": "listening"},
        provenance={"confidence": 0.85},
    )
    return {"score": asdict(score), "ingest": result}


async def run_comprehension(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    segment_id: UUID,
    expected_option_id: str,
    submitted_option_id: str,
    session_id: UUID | None = None,
    scaffold_level: int = 1,
    event_id: UUID | None = None,
    question_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    seg = await _segment_for_student(
        db, student_id=student_id, media_id=media_id, segment_id=segment_id
    )
    refs = await _knowledge_refs_for_segment(
        db, media_id=media_id, segment_id=segment_id, text=seg.text
    )
    score = score_comprehension_choice(expected_option_id, submitted_option_id)
    attempt_id = event_id or uuid4()
    await ingest_immersive_event(
        db,
        student_id=student_id,
        action="comprehension_attempt",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=uuid4(),
        session_id=session_id,
        knowledge_refs=refs,
        response={"submitted_option_id": submitted_option_id},
        intervention={"scaffold_level": scaffold_level},
        item_features={"modality": "video", "format": "comprehension"},
        advance_cognition=False,
    )
    result = await ingest_immersive_event(
        db,
        student_id=student_id,
        action="comprehension_result",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=attempt_id,
        session_id=session_id,
        knowledge_refs=refs[:1] or refs,
        response={
            "submitted_option_id": submitted_option_id,
            "expected_option_id": expected_option_id,
        },
        outcome={
            "correctness": score.correctness,
            "partial_credit": score.partial_credit,
            "verifier": score.verifier,
            "verifier_version": score.verifier_version,
        },
        intervention={"scaffold_level": scaffold_level, "ai_assisted": False},
        evaluation_phase="practice",
        item_features={"modality": "video", "format": "comprehension"},
        provenance={
            "confidence": 0.95,
            "metadata": {"question_provenance": question_provenance or {"type": "deterministic"}},
        },
    )
    return {"score": asdict(score), "ingest": result}


async def run_sentence_recall(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    segment_id: UUID,
    submitted: str,
    session_id: UUID | None = None,
    scaffold_level: int = 4,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    seg = await _segment_for_student(
        db, student_id=student_id, media_id=media_id, segment_id=segment_id
    )
    refs = await _knowledge_refs_for_segment(
        db, media_id=media_id, segment_id=segment_id, text=seg.text
    )
    score = score_dictation(seg.text, submitted)
    attempt_id = event_id or uuid4()
    await ingest_immersive_event(
        db,
        student_id=student_id,
        action="sentence_recall_attempt",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=uuid4(),
        session_id=session_id,
        knowledge_refs=refs,
        response={"submitted": submitted},
        intervention={"scaffold_level": scaffold_level},
        advance_cognition=False,
    )
    result = await ingest_immersive_event(
        db,
        student_id=student_id,
        action="sentence_recall_result",
        object_type="transcript_segment",
        object_id=str(segment_id),
        event_id=attempt_id,
        session_id=session_id,
        knowledge_refs=refs[:1] or refs,
        response={"submitted": submitted},
        outcome={
            "correctness": score.correctness,
            "partial_credit": score.partial_credit,
            "verifier": score.verifier,
            "verifier_version": score.verifier_version,
        },
        intervention={"scaffold_level": scaffold_level, "ai_assisted": False},
        evaluation_phase="practice",
        item_features={"modality": "transcript", "format": "recall"},
        provenance={"confidence": 0.9},
    )
    return {"score": asdict(score), "ingest": result}


async def run_transfer(
    db: AsyncSession,
    *,
    student_id: UUID,
    source_media_id: UUID,
    source_segment_id: UUID,
    target_media_id: UUID,
    target_segment_id: UUID,
    knowledge_ref: str,
    submitted: str,
    expected: str,
    distance: str = "near",
    session_id: UUID | None = None,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    await get_owned_media(db, student_id=student_id, media_id=source_media_id)
    await get_owned_media(db, student_id=student_id, media_id=target_media_id)
    score = score_dictation(expected, submitted)
    phase = "near_transfer" if distance != "far" else "far_transfer"
    attempt_id = event_id or uuid4()
    await ingest_immersive_event(
        db,
        student_id=student_id,
        action="transfer_attempt",
        object_type="learning_unit",
        object_id=knowledge_ref,
        event_id=uuid4(),
        session_id=session_id,
        knowledge_refs=[knowledge_ref],
        response={
            "submitted": submitted,
            "source_media_id": str(source_media_id),
            "target_media_id": str(target_media_id),
            "source_segment_id": str(source_segment_id),
            "target_segment_id": str(target_segment_id),
            "distance": distance,
        },
        advance_cognition=False,
    )
    result = await ingest_immersive_event(
        db,
        student_id=student_id,
        action="transfer_result",
        object_type="learning_unit",
        object_id=knowledge_ref,
        event_id=attempt_id,
        session_id=session_id,
        knowledge_refs=[knowledge_ref],
        response={"submitted": submitted, "distance": distance},
        outcome={
            "correctness": score.correctness,
            "partial_credit": score.partial_credit,
            "verifier": score.verifier,
            "verifier_version": score.verifier_version,
        },
        intervention={"scaffold_level": 5, "ai_assisted": False},
        evaluation_phase=phase,
        item_features={"modality": "video", "format": "transfer"},
        provenance={"confidence": 0.9},
    )
    return {"score": asdict(score), "ingest": result, "distance": distance}

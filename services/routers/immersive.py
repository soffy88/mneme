"""Immersive Learning HTTP API — gated by IMMERSIVE_LEARNING_ENABLED."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from obase.db import get_db
from services.feature_flags import immersive_learning_enabled
from services.immersive.events import ImmersiveEventError, ingest_immersive_event
from services.immersive.media_service import (
    MediaServiceError,
    append_telemetry,
    attach_transcript,
    create_media_from_upload,
    get_owned_media,
    list_segments,
    start_or_resume_session,
    update_session_continuity,
)
from services.immersive.policy import recommend_immersive_next
from services.immersive.practice import (
    run_comprehension,
    run_dictation,
    run_listening,
    run_sentence_recall,
    run_transfer,
)
from services.learning_event_service import LearningEventConflictError
from services.models import LearningUnit, LearningUnitOccurrence, MediaAsset, User
from services.observability import record_immersive_request
from services.purge_service import PurgeStorageCleanupError, delete_media_asset
from services.storage import presign_media_get_url
from services.upload_safety import UploadValidationError

router = APIRouter(prefix="/v2/immersive", tags=["immersive"])


def _require_flag() -> None:
    if not immersive_learning_enabled():
        raise HTTPException(status_code=404, detail="immersive learning disabled")


class TelemetryBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    media_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class TelemetryBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryBatchItem]


class ContinuityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playhead_ms: int | None = None
    current_segment_id: UUID | None = None
    scaffold_level: int | None = None
    state: str | None = None


class LearningEventIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    object_type: str
    object_id: str
    event_id: UUID | None = None
    session_id: UUID | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    response: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    process_signals: dict[str, Any] | None = None
    intervention: dict[str, Any] | None = None
    evaluation_phase: str | None = None
    item_features: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    explicit_practice: bool = False
    occurred_at: datetime | None = None


class DictationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    segment_id: UUID
    submitted: str
    session_id: UUID | None = None
    scaffold_level: int = 3
    event_id: UUID | None = None


class ListeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    segment_id: UUID
    submitted_meaning: str
    session_id: UUID | None = None
    scaffold_level: int = 3
    event_id: UUID | None = None


class ComprehensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    segment_id: UUID
    expected_option_id: str
    submitted_option_id: str
    session_id: UUID | None = None
    scaffold_level: int = 1
    event_id: UUID | None = None
    question_provenance: dict[str, Any] | None = None


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    segment_id: UUID
    submitted: str
    session_id: UUID | None = None
    scaffold_level: int = 4
    event_id: UUID | None = None


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_media_id: UUID
    source_segment_id: UUID
    target_media_id: UUID
    target_segment_id: UUID
    knowledge_ref: str
    submitted: str
    expected: str
    distance: str = "near"
    session_id: UUID | None = None
    event_id: UUID | None = None


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_scaffold: int = 0
    mastery: float | None = None
    evidence_count: int = 0
    due_urgency: float = 0.0
    transfer_need: float = 0.0
    recent_override: bool = False
    epistemic_uncertainty: float | None = None


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    segment_id: UUID
    text: str
    nearby: list[str] = Field(default_factory=list)


@router.get("/status")
async def immersive_status() -> dict[str, Any]:
    """Always reachable — reports flag without leaking disabled routes' shapes."""

    return {"enabled": immersive_learning_enabled()}


@router.post("/{student_id}/media")
async def upload_media(
    student_id: UUID,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    language: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    record_immersive_request("upload_media")
    try:
        data = await file.read()
        asset = await create_media_from_upload(
            db,
            student_id=student_id,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            title=title,
            language=language,
        )
        await db.commit()
        return {
            "media_id": str(asset.id),
            "media_type": asset.media_type,
            "title": asset.title,
            "storage_ref": asset.storage_ref,
            "content_provenance": asset.content_provenance,
        }
    except (UploadValidationError, MediaServiceError) as exc:
        await db.rollback()
        status = getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/{student_id}/media")
async def list_media(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    rows = (
        await db.execute(
            select(MediaAsset)
            .where(MediaAsset.owner_student_id == student_id)
            .order_by(MediaAsset.created_at.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "media_id": str(row.id),
                "title": row.title,
                "media_type": row.media_type,
                "language": row.language,
                "duration_ms": row.duration_ms,
                "content_provenance": row.content_provenance,
                "processing_state": row.processing_state,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/{student_id}/media/{media_id}")
async def get_media(
    student_id: UUID,
    media_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    try:
        asset = await get_owned_media(db, student_id=student_id, media_id=media_id)
    except MediaServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    playback_url = None
    if asset.storage_ref:
        try:
            playback_url = presign_media_get_url(asset.storage_ref)
        except Exception:  # noqa: BLE001
            playback_url = None
    return {
        "media_id": str(asset.id),
        "title": asset.title,
        "media_type": asset.media_type,
        "language": asset.language,
        "duration_ms": asset.duration_ms,
        "content_provenance": asset.content_provenance,
        "playback_url": playback_url,
        # storage_ref intentionally not a signed URL identity
        "has_storage": bool(asset.storage_ref),
    }


@router.delete("/{student_id}/media/{media_id}")
async def delete_media(
    student_id: UUID,
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await delete_media_asset(db, student_id, media_id)
        await db.commit()
        return result
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PurgeStorageCleanupError as exc:
        await db.commit()
        raise HTTPException(
            status_code=202,
            detail={"deleted": True, "storage_cleanup_pending": list(exc.args[0])},
        ) from exc


@router.post("/{student_id}/media/{media_id}/transcript")
async def upload_transcript(
    student_id: UUID,
    media_id: UUID,
    file: UploadFile = File(...),
    language: str | None = Form(None),
    role: str = Form("PRIMARY"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        content = (await file.read()).decode("utf-8", errors="replace")
        result = await attach_transcript(
            db,
            student_id=student_id,
            media_id=media_id,
            content=content,
            filename=file.filename,
            language=language,
            role=role.upper(),
        )
        await db.commit()
        return result
    except (UnicodeError, MediaServiceError, UploadValidationError) as exc:
        await db.rollback()
        status = getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/{student_id}/media/{media_id}/segments")
async def get_segments(
    student_id: UUID,
    media_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    try:
        return await list_segments(
            db, student_id=student_id, media_id=media_id, offset=offset, limit=limit
        )
    except MediaServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{student_id}/media/{media_id}/session")
async def open_session(
    student_id: UUID,
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        session = await start_or_resume_session(
            db, student_id=student_id, media_id=media_id
        )
        await db.commit()
        return {
            "session_id": str(session.id),
            "media_id": str(session.media_id),
            "playhead_ms": session.playhead_ms,
            "current_segment_id": str(session.current_segment_id)
            if session.current_segment_id
            else None,
            "scaffold_level": session.scaffold_level,
            "state": session.state,
            "note": "playhead is continuity only; not CognitiveState",
        }
    except MediaServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/{student_id}/sessions/{session_id}")
async def patch_session(
    student_id: UUID,
    session_id: UUID,
    body: ContinuityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        session = await update_session_continuity(
            db,
            student_id=student_id,
            session_id=session_id,
            playhead_ms=body.playhead_ms,
            current_segment_id=body.current_segment_id,
            scaffold_level=body.scaffold_level,
            state=body.state,
        )
        await db.commit()
        return {
            "session_id": str(session.id),
            "playhead_ms": session.playhead_ms,
            "current_segment_id": str(session.current_segment_id)
            if session.current_segment_id
            else None,
            "scaffold_level": session.scaffold_level,
            "state": session.state,
        }
    except MediaServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{student_id}/telemetry")
async def post_telemetry(
    student_id: UUID,
    body: TelemetryBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    ids: list[str] = []
    try:
        for item in body.events[:200]:
            tid = await append_telemetry(
                db,
                student_id=student_id,
                event_type=item.event_type,
                media_id=item.media_id,
                session_id=item.session_id,
                payload=item.payload,
                occurred_at=item.occurred_at,
            )
            ids.append(str(tid))
        await db.commit()
        return {"inserted": len(ids), "ids": ids, "plane": "telemetry"}
    except MediaServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{student_id}/events")
async def post_learning_event(
    student_id: UUID,
    body: LearningEventIngestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await ingest_immersive_event(
            db,
            student_id=student_id,
            action=body.action,
            object_type=body.object_type,
            object_id=body.object_id,
            event_id=body.event_id,
            session_id=body.session_id,
            knowledge_refs=body.knowledge_refs,
            response=body.response,
            outcome=body.outcome,
            process_signals=body.process_signals,
            intervention=body.intervention,
            evaluation_phase=body.evaluation_phase,
            item_features=body.item_features,
            provenance=body.provenance,
            explicit_practice=body.explicit_practice,
            occurred_at=body.occurred_at,
        )
        await db.commit()
        return result
    except LearningEventConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImmersiveEventError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{student_id}/practice/dictation")
async def practice_dictation(
    student_id: UUID,
    body: DictationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await run_dictation(
            db,
            student_id=student_id,
            media_id=body.media_id,
            segment_id=body.segment_id,
            submitted=body.submitted,
            session_id=body.session_id,
            scaffold_level=body.scaffold_level,
            event_id=body.event_id,
        )
        await db.commit()
        return result
    except (MediaServiceError, ImmersiveEventError, LearningEventConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, LearningEventConflictError) else getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{student_id}/practice/listening")
async def practice_listening(
    student_id: UUID,
    body: ListeningRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await run_listening(
            db,
            student_id=student_id,
            media_id=body.media_id,
            segment_id=body.segment_id,
            submitted_meaning=body.submitted_meaning,
            session_id=body.session_id,
            scaffold_level=body.scaffold_level,
            event_id=body.event_id,
        )
        await db.commit()
        return result
    except (MediaServiceError, ImmersiveEventError, LearningEventConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, LearningEventConflictError) else getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{student_id}/practice/comprehension")
async def practice_comprehension(
    student_id: UUID,
    body: ComprehensionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await run_comprehension(
            db,
            student_id=student_id,
            media_id=body.media_id,
            segment_id=body.segment_id,
            expected_option_id=body.expected_option_id,
            submitted_option_id=body.submitted_option_id,
            session_id=body.session_id,
            scaffold_level=body.scaffold_level,
            event_id=body.event_id,
            question_provenance=body.question_provenance,
        )
        await db.commit()
        return result
    except (MediaServiceError, ImmersiveEventError, LearningEventConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, LearningEventConflictError) else getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{student_id}/practice/recall")
async def practice_recall(
    student_id: UUID,
    body: RecallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await run_sentence_recall(
            db,
            student_id=student_id,
            media_id=body.media_id,
            segment_id=body.segment_id,
            submitted=body.submitted,
            session_id=body.session_id,
            scaffold_level=body.scaffold_level,
            event_id=body.event_id,
        )
        await db.commit()
        return result
    except (MediaServiceError, ImmersiveEventError, LearningEventConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, LearningEventConflictError) else getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{student_id}/practice/transfer")
async def practice_transfer(
    student_id: UUID,
    body: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_flag()
    _ensure_student_self(current_user, student_id)
    try:
        result = await run_transfer(
            db,
            student_id=student_id,
            source_media_id=body.source_media_id,
            source_segment_id=body.source_segment_id,
            target_media_id=body.target_media_id,
            target_segment_id=body.target_segment_id,
            knowledge_ref=body.knowledge_ref,
            submitted=body.submitted,
            expected=body.expected,
            distance=body.distance,
            session_id=body.session_id,
            event_id=body.event_id,
        )
        await db.commit()
        return result
    except (MediaServiceError, ImmersiveEventError, LearningEventConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, LearningEventConflictError) else getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{student_id}/policy/recommend")
async def policy_recommend(
    student_id: UUID,
    body: PolicyRequest,
    _auth: User = Depends(require_student_access),
):
    _require_flag()
    result = recommend_immersive_next(
        student_id=student_id,
        current_scaffold=body.current_scaffold,
        mastery=body.mastery,
        evidence_count=body.evidence_count,
        due_urgency=body.due_urgency,
        transfer_need=body.transfer_need,
        recent_override=body.recent_override,
        epistemic_uncertainty=body.epistemic_uncertainty,
    )
    return result.as_dict()


@router.get("/{student_id}/learning-units/{stable_key}/occurrences")
async def learning_unit_occurrences(
    student_id: UUID,
    stable_key: str,
    kind: str = Query("VOCABULARY"),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """Prove cross-media LearningUnit identity for transfer."""

    _require_flag()
    unit = (
        await db.execute(
            select(LearningUnit).where(
                LearningUnit.kind == kind,
                LearningUnit.stable_key == stable_key,
            )
        )
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(status_code=404, detail="learning unit not found")
    occ = (
        await db.execute(
            select(LearningUnitOccurrence, MediaAsset)
            .join(MediaAsset, MediaAsset.id == LearningUnitOccurrence.media_id)
            .where(
                LearningUnitOccurrence.learning_unit_id == unit.id,
                MediaAsset.owner_student_id == student_id,
            )
        )
    ).all()
    return {
        "learning_unit_id": str(unit.id),
        "kind": unit.kind,
        "stable_key": unit.stable_key,
        "display_text": unit.display_text,
        "occurrences": [
            {
                "occurrence_id": str(row.LearningUnitOccurrence.id),
                "media_id": str(row.LearningUnitOccurrence.media_id),
                "segment_id": str(row.LearningUnitOccurrence.segment_id),
                "surface_form": row.LearningUnitOccurrence.surface_form,
                "media_title": row.MediaAsset.title,
            }
            for row in occ
        ],
    }


@router.post("/{student_id}/explain")
async def explain_sentence(
    student_id: UUID,
    body: ExplainRequest,
    _auth: User = Depends(require_student_access),
):
    """Graceful sentence explanation — never writes mastery."""

    _require_flag()
    # Prefer existing LLM provider if present; otherwise degrade.
    try:
        from services.immersive.explain import explain_sentence_safe

        return await explain_sentence_safe(
            student_id=student_id,
            media_id=body.media_id,
            segment_id=body.segment_id,
            text=body.text,
            nearby=body.nearby,
        )
    except Exception:  # noqa: BLE001
        return {
            "status": "degraded",
            "explanation": None,
            "message": "explanation provider unavailable; player remains usable",
            "mastery_modified": False,
        }

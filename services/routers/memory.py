"""Blueprint v2 memory, learner-state, replay, export and policy boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from event_schema import LearningEvent, export_events, legacy_interaction_to_event
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.evidence_graph import (
    append_event_evidence,
    claim_evidence_payload,
    redact_event_for_parent,
)
from services.cognitive_state_v2 import (
    explain_cognitive_state,
    get_cognitive_state_with_evidence,
    get_independent_mastery_evidence,
)
from services.learning_event_replay_service import (
    ReplayConfig,
    replay_student_from_db,
)
from services.learning_event_service import (
    LearningEventConflictError,
    append_learning_event,
)
from services.learner_state_service import get_learner_state, growth_summary
from services.models import (
    InteractionEvent,
    LearningEventRecord,
    MemoryClaim,
    MemoryClaimEvidence,
    MemoryEvidence,
    PolicyDecisionRecord,
    User,
)

router = APIRouter(tags=["memory-v2"])


class ReplayRequest(BaseModel):
    student_id: UUID
    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None
    min_review_interval_hours: float = Field(default=0.0, ge=0.0)


class ExportRequest(BaseModel):
    student_id: UUID
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    format: Literal["mneme", "xapi", "caliper", "case"] = "mneme"

    model_config = {"populate_by_name": True}


def _event_payload(
    event: LearningEvent,
    *,
    redact: bool,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = event.model_dump(mode="json", exclude_none=False)
    payload["evidence_ids"] = evidence_ids or []
    return redact_event_for_parent(payload) if redact else payload


async def _event_evidence_ids(
    db: AsyncSession,
    student_id: UUID,
    events: tuple[LearningEvent, ...],
) -> dict[UUID, list[str]]:
    event_ids = [event.event_id for event in events]
    if not event_ids:
        return {}
    rows = (
        await db.execute(
            select(MemoryEvidence.source_event_id, MemoryEvidence.id).where(
                MemoryEvidence.student_id == student_id,
                MemoryEvidence.source_event_id.in_(event_ids),
            )
        )
    ).all()
    result: dict[UUID, list[str]] = {}
    for source_event_id, evidence_id in rows:
        if source_event_id is not None:
            result.setdefault(source_event_id, []).append(str(evidence_id))
    return result


async def _timeline_events(
    db: AsyncSession,
    student_id: UUID,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> tuple[LearningEvent, ...]:
    """Merge v2 facts with legacy rows during the dual-write transition."""

    v2_stmt = select(LearningEventRecord).where(
        LearningEventRecord.student_id == student_id
    )
    if start is not None:
        v2_stmt = v2_stmt.where(LearningEventRecord.occurred_at >= start)
    if end is not None:
        v2_stmt = v2_stmt.where(LearningEventRecord.occurred_at < end)
    v2_rows = (await db.execute(v2_stmt)).scalars().all()
    events = [
        LearningEvent.model_validate(
            {
                "event_id": row.event_id,
                "schema_version": row.schema_version,
                "actor_id": row.actor_id,
                "student_id": row.student_id,
                "session_id": row.session_id,
                "occurred_at": row.occurred_at,
                "received_at": row.received_at,
                "source": row.source,
                "action": row.action,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "content_version": row.content_version,
                "knowledge_refs": row.knowledge_refs,
                "item_features": row.item_features,
                "response": row.response,
                "outcome": row.outcome,
                "process_signals": row.process_signals,
                "metacognitive": row.metacognitive,
                "intervention": row.intervention,
                "evaluation_phase": row.evaluation_phase,
                "provenance": row.provenance,
                "privacy_class": row.privacy_class,
                "trace_id": row.trace_id,
                "supersedes_event_id": row.supersedes_event_id,
                "correction_reason": row.correction_reason,
            }
        )
        for row in v2_rows
    ]
    known_ids = {event.event_id for event in events}

    legacy_stmt = select(InteractionEvent).where(
        InteractionEvent.student_id == student_id
    )
    if start is not None:
        legacy_stmt = legacy_stmt.where(InteractionEvent.occurred_at >= start)
    if end is not None:
        legacy_stmt = legacy_stmt.where(InteractionEvent.occurred_at < end)
    legacy_rows = (await db.execute(legacy_stmt)).scalars().all()
    for row in legacy_rows:
        event = legacy_interaction_to_event(row)
        if event.event_id not in known_ids:
            events.append(event)
    events.sort(key=lambda event: (event.occurred_at, event.received_at, event.event_id.hex))
    return tuple(events[-limit:])


async def _can_share_process(
    db: AsyncSession, student_id: UUID, current_user: User
) -> bool:
    if current_user.id == student_id:
        return True
    share = (
        await db.execute(select(User.share_process_with_parent).where(User.id == student_id))
    ).scalar_one_or_none()
    return bool(share)


@router.get("/v2/memory/timeline")
async def get_memory_timeline(
    student_id: UUID = Query(...),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    events = await _timeline_events(
        db, student_id, start=from_, end=to, limit=limit
    )
    redact = not await _can_share_process(db, student_id, current_user)
    evidence_ids = await _event_evidence_ids(db, student_id, events)
    return {
        "student_id": str(student_id),
        "from": from_.isoformat() if from_ else None,
        "to": to.isoformat() if to else None,
        "count": len(events),
        "events": [
            _event_payload(
                event, redact=redact, evidence_ids=evidence_ids.get(event.event_id)
            )
            for event in events
        ],
    }


@router.get("/v2/memory/claims")
async def list_memory_claims(
    student_id: UUID = Query(...),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """List evidence-grounded memory claims without exposing process data by default."""

    claims = (
        await db.execute(
            select(MemoryClaim)
            .where(MemoryClaim.student_id == student_id)
            .order_by(MemoryClaim.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not claims:
        return {"student_id": str(student_id), "count": 0, "claims": []}

    claim_ids = [claim.id for claim in claims]
    evidence_counts = (
        await db.execute(
            select(MemoryClaimEvidence.claim_id, func.count(MemoryClaimEvidence.evidence_id))
            .where(MemoryClaimEvidence.claim_id.in_(claim_ids))
            .group_by(MemoryClaimEvidence.claim_id)
        )
    ).all()
    counts = {claim_id: int(count) for claim_id, count in evidence_counts}
    redact = not await _can_share_process(db, student_id, current_user)
    return {
        "student_id": str(student_id),
        "count": len(claims),
        "claims": [
            {
                "id": str(claim.id),
                "claim_type": claim.claim_type,
                "subject_type": claim.subject_type,
                "subject_id": claim.subject_id,
                "claim_text": (
                    "[redacted]"
                    if redact and claim.privacy_class in {"P2", "P3"}
                    else claim.claim_text
                ),
                "confidence": claim.confidence,
                "model_version": claim.model_version,
                "privacy_class": claim.privacy_class,
                "evidence_count": counts.get(claim.id, 0),
                "created_at": claim.created_at.isoformat() if claim.created_at else None,
            }
            for claim in claims
        ],
    }


@router.get("/v2/memory/evidence/{claim_id}")
async def get_memory_evidence(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    claim = (
        await db.execute(select(MemoryClaim).where(MemoryClaim.id == claim_id))
    ).scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="Memory claim not found")
    await _ensure_student_access(db, current_user, claim.student_id)
    rows = (
        await db.execute(
            select(MemoryClaimEvidence, MemoryEvidence)
            .join(MemoryEvidence, MemoryEvidence.id == MemoryClaimEvidence.evidence_id)
            .where(
                MemoryClaimEvidence.claim_id == claim_id,
                MemoryEvidence.student_id == claim.student_id,
            )
            .order_by(MemoryEvidence.occurred_at, MemoryEvidence.id)
        )
    ).all()
    evidence_rows = [(row[0], row[1]) for row in rows]
    payload = claim_evidence_payload(claim, evidence_rows)
    if not await _can_share_process(db, claim.student_id, current_user):
        if claim.privacy_class in {"P2", "P3"}:
            payload["claim"]["claim_text"] = "[redacted]"
            payload["claim"]["provenance"] = {}
        for evidence in payload["evidence"]:
            if evidence["privacy_class"] in {"P2", "P3"}:
                evidence["payload"] = {"redacted": True}
    return payload


@router.post("/v2/events")
async def post_learning_event(
    event: LearningEvent,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if event.student_id is None:
        raise HTTPException(status_code=422, detail="student_id is required")
    _ensure_student_self(current_user, event.student_id)
    try:
        result = await append_learning_event(db, event)
        evidence_id = await append_event_evidence(db, event)
        await db.commit()
    except LearningEventConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "event_id": str(result.event_id),
        "evidence_id": str(evidence_id),
        "inserted": result.inserted,
        "checksum": result.checksum,
    }


@router.get("/v2/learner-state/{student_id}")
async def get_student_learner_state(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return await get_learner_state(db, student_id)


@router.get("/v2/learner-state/{student_id}/ku/{ku_id}")
async def get_student_ku_state(
    student_id: UUID,
    ku_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return await get_learner_state(db, student_id, ku_id=ku_id)


@router.get("/v2/growth/{student_id}/period/{term}")
async def get_growth_period(
    student_id: UUID,
    term: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await growth_summary(db, student_id, term)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/cognitive-state/{student_id}/{knowledge_ref}")
async def get_cognitive_state(
    student_id: UUID,
    knowledge_ref: str,
    as_of: datetime | None = Query(default=None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return await get_cognitive_state_with_evidence(
        db, student_id, knowledge_ref, as_of=as_of
    )


@router.get("/v2/cognitive-state/{student_id}/{knowledge_ref}/explain")
async def explain_cognitive_state_route(
    student_id: UUID,
    knowledge_ref: str,
    as_of: datetime | None = Query(default=None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    state = await get_cognitive_state_with_evidence(
        db, student_id, knowledge_ref, as_of=as_of
    )
    return explain_cognitive_state(state)


@router.get("/v2/evidence/independent/{student_id}")
async def get_independent_evidence(
    student_id: UUID,
    knowledge_ref: str | None = Query(default=None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    return {
        "student_id": str(student_id),
        "evidence": await get_independent_mastery_evidence(
            db, student_id, knowledge_ref
        ),
    }


@router.post("/v2/replay")
async def post_replay(
    body: ReplayRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_student_access(db, current_user, body.student_id)
    projection = await replay_student_from_db(
        db,
        body.student_id,
        config=ReplayConfig(min_review_interval_hours=body.min_review_interval_hours),
        start=body.start,
        end=body.end,
        as_of=body.as_of,
    )
    return projection.as_dict()


@router.post("/v2/export")
async def post_memory_export(
    body: ExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_student_access(db, current_user, body.student_id)
    state = await get_learner_state(db, body.student_id)
    events = await _timeline_events(
        db,
        body.student_id,
        start=body.from_,
        end=body.to,
        limit=10000,
    )
    redact = not await _can_share_process(db, body.student_id, current_user)
    evidence_ids = await _event_evidence_ids(db, body.student_id, events)
    claims = (
        await db.execute(
            select(MemoryClaim)
            .where(MemoryClaim.student_id == body.student_id)
            .order_by(MemoryClaim.created_at)
        )
    ).scalars().all()
    policy_decisions = (
        await db.execute(
            select(PolicyDecisionRecord)
            .where(PolicyDecisionRecord.student_id == body.student_id)
            .order_by(PolicyDecisionRecord.timestamp, PolicyDecisionRecord.decision_id)
        )
    ).scalars().all()
    if body.format != "mneme":
        return {
            "export_version": f"{body.format}/v1",
            "format": body.format,
            "student_id": str(body.student_id),
            "events": export_events(
                events,
                body.format,
                redact_private=redact,
            ),
        }

    return {
        "export_version": "mneme-memory-export/v2",
        "format": body.format,
        "student_id": str(body.student_id),
        "learner_state": state,
        "events": [
            _event_payload(
                event,
                redact=redact,
                evidence_ids=evidence_ids.get(event.event_id),
            )
            for event in events
        ],
        "claims": [
            {
                "id": str(claim.id),
                "claim_type": claim.claim_type,
                "subject_type": claim.subject_type,
                "subject_id": claim.subject_id,
                "claim_text": (
                    "[redacted]"
                    if redact and claim.privacy_class in {"P2", "P3"}
                    else claim.claim_text
                ),
                "confidence": claim.confidence,
                "model_version": claim.model_version,
                "privacy_class": claim.privacy_class,
                "created_at": claim.created_at.isoformat() if claim.created_at else None,
            }
            for claim in claims
        ],
        "policy_decisions": [
            {
                "decision_id": str(decision.decision_id),
                "timestamp": decision.timestamp.isoformat(),
                "candidate_actions": decision.candidate_actions,
                "selected_action": decision.selected_action,
                "reason_codes": decision.reason_codes,
                "state_version": decision.state_version,
                "policy_version": decision.policy_version,
                "evidence_refs": decision.evidence_refs,
                "constraints": decision.constraints,
                "expected_utility": decision.expected_utility,
                "exploration_flag": decision.exploration_flag,
                "fallback_reason": decision.fallback_reason,
                "evidence_level": decision.evidence_level,
                "trace_id": decision.trace_id,
            }
            for decision in policy_decisions
        ],
    }


@router.get("/v2/policy/next-action/{student_id}")
async def get_next_action(
    student_id: UUID,
    request: Request,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    from services.policy_service import next_best_action
    from services.policy_trace import persist_policy_decision

    result = await next_best_action(db, student_id)
    from services.observability import record_policy_decision

    record_policy_decision(
        fallback=bool(result.get("policy_decision", {}).get("fallback_reason"))
    )
    trace = result.get("policy_decision")
    if trace is not None:
        from services.policy_trace import PolicyDecision

        trace["trace_id"] = getattr(request.state, "trace_id", None)
        await persist_policy_decision(db, PolicyDecision.model_validate(trace))
        await db.commit()
    return result

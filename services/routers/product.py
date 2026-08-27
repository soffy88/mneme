"""Minimal product surfaces over the existing LearningEvent/state/policy APIs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import _ensure_student_self, get_current_user, require_student_access
from services.cognitive_state_v2 import CognitiveStateV2
from services.daily_plan_service import build_daily_plan
from services.feature_flags import notifications_enabled
from services.learning_event_service import learning_event_record_to_event
from services.models import (
    InteractionEvent,
    LearningEventRecord,
    PilotMeasurementSchedule,
    PolicyDecisionRecord,
    User,
)
from services.policy_service import next_best_action
from services.policy_trace import PolicyDecision, persist_policy_decision
from services.product_closure import (
    ProductEventType,
    append_product_learning_event,
    advance_first_value_state,
    build_learn_now,
    build_notification_contract,
    build_session_summary,
    build_today_queue,
    check_entitlement,
    compute_cohort_analytics,
    compute_commercial_metrics,
    compute_flywheel_health,
    compute_product_analytics,
    create_product_learning_event,
    get_return_reason,
    project_memory,
    project_progress,
)

router = APIRouter(tags=["product"])


class ProductEventRequest(BaseModel):
    event_type: ProductEventType
    occurred_at: datetime
    session_id: UUID | None = None
    knowledge_refs: list[str] = Field(default_factory=list, max_length=20)
    policy_decision_id: UUID | None = None


def _event_rows_to_events(rows: list[LearningEventRecord]) -> list[object]:
    return [learning_event_record_to_event(row) for row in rows]


async def _student_events(db: AsyncSession, student_id: UUID) -> list[object]:
    rows = (
        await db.execute(
            select(LearningEventRecord)
            .where(LearningEventRecord.student_id == student_id)
            .order_by(LearningEventRecord.occurred_at, LearningEventRecord.event_id)
        )
    ).scalars().all()
    # Product views may operate during the gradual v2 dual-write rollout. The
    # legacy adapter preserves facts without treating the old table as a new
    # event system; when both exist, retain both fact streams and deduplicate by
    # event ID.
    from event_schema import legacy_interaction_to_event

    legacy = (
        await db.execute(
            select(InteractionEvent)
            .where(InteractionEvent.student_id == student_id)
            .order_by(InteractionEvent.occurred_at, InteractionEvent.id)
        )
    ).scalars().all()
    result: list[object] = _event_rows_to_events(list(rows))
    seen = {str(getattr(event, "event_id", "")) for event in result}
    result.extend(
        event
        for event in (legacy_interaction_to_event(row) for row in legacy)
        if str(getattr(event, "event_id", "")) not in seen
    )
    return sorted(result, key=lambda event: (getattr(event, "occurred_at"), str(getattr(event, "event_id", ""))))


async def _persist_decision(db: AsyncSession, result: dict) -> PolicyDecision:
    decision = PolicyDecision.model_validate(result["policy_decision"])
    await persist_policy_decision(db, decision)
    await db.commit()
    return decision


@router.post("/v2/product/events/{student_id}", status_code=201)
async def post_product_event(
    student_id: UUID,
    body: ProductEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a product action as a real LearningEvent; clients cannot mark it synthetic."""

    _ensure_student_self(current_user, student_id)
    try:
        event = create_product_learning_event(
            student_id=student_id,
            event_type=body.event_type,
            occurred_at=body.occurred_at,
            session_id=body.session_id,
            knowledge_refs=body.knowledge_refs,
            policy_decision_id=body.policy_decision_id,
            trace_id=None,
        )
        result = await append_product_learning_event(db, event)
        await db.commit()
        return {"event_id": str(result.event_id), "inserted": result.inserted, "event_type": body.event_type.value}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v2/product/learn-now/{student_id}")
async def get_learn_now(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    result = await next_best_action(db, student_id)
    decision = await _persist_decision(db, result)
    return build_learn_now(decision).model_dump(mode="json") | {"policy_decision": decision.model_dump(mode="json")}


@router.get("/v2/product/first-value/{student_id}")
async def get_first_value(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    from services.models import KCMastery

    events = await _student_events(db, student_id)
    has_state = bool(
        (
            await db.execute(select(KCMastery.id).where(KCMastery.student_id == student_id).limit(1))
        ).scalar_one_or_none()
    )
    has_policy = bool(
        (
            await db.execute(select(PolicyDecisionRecord.decision_id).where(PolicyDecisionRecord.student_id == student_id).limit(1))
        ).scalar_one_or_none()
    )
    state = advance_first_value_state(
        events,
        cognitive_state_available=has_state,
        policy_decision_available=has_policy,
    )
    return state.model_dump(mode="json")


@router.get("/v2/product/today/{student_id}")
async def get_today_queue(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    result = await next_best_action(db, student_id)
    decision = await _persist_decision(db, result)
    plan = await build_daily_plan(db, student_id)
    tasks = [dict(task) for task in plan.get("tasks", [])]
    for index, task in enumerate(tasks):
        task["candidate_id"] = f"{task.get('type', 'task')}:{task.get('subject', 'all')}:{index}"
    return build_today_queue(tasks, decision).model_dump(mode="json")


@router.get("/v2/product/memory/{student_id}")
async def get_memory_projection(
    student_id: UUID,
    advanced: bool = Query(False),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    from services.models import KCMastery

    masteries = (
        await db.execute(
            select(KCMastery).where(KCMastery.student_id == student_id)
        )
    ).scalars().all()
    projections = []
    for mastery in masteries:
        state = await CognitiveStateV2.rebuild(db, student_id, mastery.knowledge_point)
        projections.append(project_memory(state, knowledge_ref=mastery.knowledge_point, advanced=advanced).model_dump(mode="json"))
    return {"items": projections, "status": "NO DATA" if not projections else "READY"}


@router.get("/v2/product/weak-areas/{student_id}")
async def get_weak_areas(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    from services.models import KCMastery
    from services.product_closure import project_misconceptions

    masteries = (
        await db.execute(select(KCMastery).where(KCMastery.student_id == student_id))
    ).scalars().all()
    claims = []
    for mastery in masteries:
        state = await CognitiveStateV2.rebuild(db, student_id, mastery.knowledge_point)
        claims.extend(state.evidence_claims)
    items = [item.model_dump(mode="json") for item in project_misconceptions(claims)]
    return {"items": items, "status": "NO DATA" if not items else "READY"}


@router.get("/v2/product/progress/{student_id}")
async def get_product_progress(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    events = await _student_events(db, student_id)
    return project_progress(events).model_dump(mode="json")


@router.get("/v2/product/return-reason/{student_id}")
async def get_product_return_reason(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    events = await _student_events(db, student_id)
    schedules = (
        await db.execute(
            select(PilotMeasurementSchedule).where(PilotMeasurementSchedule.student_id == student_id)
        )
    ).scalars().all()
    result = get_return_reason(events=events, schedules=schedules)
    notification = build_notification_contract(result, notifications_enabled=notifications_enabled())
    return {"return_reason": result.model_dump(mode="json"), "notification": notification.model_dump(mode="json")}


@router.get("/v2/product/session-summary/{student_id}")
async def get_product_session_summary(
    student_id: UUID,
    session_id: UUID | None = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    events = await _student_events(db, student_id)
    if session_id is not None:
        events = [event for event in events if str(getattr(event, "session_id", "")) == str(session_id)]
    return build_session_summary(events).model_dump(mode="json")


@router.get("/v2/product/entitlement/{capability}")
async def get_entitlement(
    capability: str,
    current_user: User = Depends(get_current_user),
):
    return check_entitlement(current_user, capability).model_dump(mode="json")


@router.get("/v2/product/dashboard")
async def get_product_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from obase.admin_identity import is_admin

    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可访问产品 dashboard")
    rows = (
        await db.execute(select(LearningEventRecord).order_by(LearningEventRecord.occurred_at, LearningEventRecord.event_id))
    ).scalars().all()
    events = _event_rows_to_events(list(rows))
    decisions = (await db.execute(select(PolicyDecisionRecord))).scalars().all()
    product = compute_product_analytics(events)
    cohort = compute_cohort_analytics(events, cohort_basis="signup")
    flywheel = compute_flywheel_health(interactions=events, events=events, policy_decisions=decisions)
    commercial = compute_commercial_metrics()
    return {
        "product": product.model_dump(mode="json"),
        "cohort": cohort.model_dump(mode="json"),
        "flywheel": flywheel.model_dump(mode="json"),
        "commercial": commercial.model_dump(mode="json"),
        "data_state": "NO REAL USER DATA" if not events else "REAL",
    }


__all__ = ["router"]

"""Product closure contracts built on Mneme's existing event/state/policy layers.

This module is intentionally a product adapter, not a second learner model or
analytics store.  Product views are projections of LearningEvent, Cognitive
State, PolicyDecision and pilot/evaluation evidence.  Missing real data stays
missing; synthetic/demo rows are explicitly excluded from user and commercial
claims.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from event_schema import (
    EventOutcome,
    EventProvenance,
    LearningEvent,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


PRODUCT_CONTRACT_VERSION = "product-closure/v1"
PRODUCT_RETENTION_NOTE = "PRODUCT RETENTION is return behavior; it is not learning retention."
MEMORY_LABEL_THRESHOLDS = {
    "strong_mastery": 0.80,
    "fading_retrievability": 0.40,
    "high_uncertainty": 0.30,
    "sufficient_evidence": 0.40,
}
MIN_PRODUCT_EVIDENCE = 1


class ProductEventType(str, Enum):
    CONTENT_READY = "content_ready"
    LEARNING_SESSION_STARTED = "learning_session_started"
    FIRST_VALUE_COMPLETED = "first_value_completed"
    NEXT_BEST_ACTION_STARTED = "next_best_action_started"
    NEXT_BEST_ACTION_COMPLETED = "next_best_action_completed"
    LEARNING_SESSION_COMPLETED = "learning_session_completed"
    RETURN_REASON_PRESENTED = "return_reason_presented"
    REVIEW_COMPLETED = "review_completed"
    INDEPENDENT_TEST_COMPLETED = "independent_test_completed"


class FirstValueStage(str, Enum):
    NEW = "NEW"
    CONTENT_READY = "CONTENT_READY"
    FIRST_ATTEMPT = "FIRST_ATTEMPT"
    FIRST_STATE = "FIRST_STATE"
    FIRST_RECOMMENDATION = "FIRST_RECOMMENDATION"
    FIRST_VALUE_COMPLETE = "FIRST_VALUE_COMPLETE"


class ReturnReason(str, Enum):
    REVIEW_DUE = "REVIEW_DUE"
    MEMORY_FADING = "MEMORY_FADING"
    CONTINUE_LEARNING = "CONTINUE_LEARNING"
    MISCONCEPTION_REPAIR = "MISCONCEPTION_REPAIR"
    TRANSFER_CHECK = "TRANSFER_CHECK"
    DELAYED_TEST_DUE = "DELAYED_TEST_DUE"
    NONE = "NONE"


class NotificationReason(str, Enum):
    REVIEW_DUE = "REVIEW_DUE"
    MEMORY_FADING = "MEMORY_FADING"
    DELAYED_TEST_DUE = "DELAYED_TEST_DUE"
    LEARNING_PLAN_READY = "LEARNING_PLAN_READY"


class Plan(str, Enum):
    FREE = "FREE"
    PRO = "PRO"


class SubscriptionStatus(str, Enum):
    NONE = "NONE"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"


class EvidenceMode(str, Enum):
    REAL = "REAL"
    OFFLINE = "OFFLINE"
    SYNTHETIC = "SYNTHETIC"
    NO_DATA = "NO DATA"


class ContaminationStatus(str, Enum):
    CLEAN = "CLEAN"
    AI_ASSISTED = "AI_ASSISTED"
    HINT_ASSISTED = "HINT_ASSISTED"
    ANSWER_EXPOSED = "ANSWER_EXPOSED"
    INVALIDATED = "INVALIDATED"
    UNKNOWN = "UNKNOWN"


class FirstValueState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: FirstValueStage = FirstValueStage.NEW
    started_at: datetime | None = None
    completed_at: datetime | None = None
    time_to_first_value_seconds: float | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "FirstValueState":
        for value in (self.started_at, self.completed_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("first-value timestamps must be timezone-aware")
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValueError("first-value completion cannot precede start")
        return self


class LearnNowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    selected_action: dict[str, Any] | None = None
    policy_decision_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    why_this: list[dict[str, Any]] = Field(default_factory=list)


class TodayQueue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    message: str | None = None
    policy_decision_id: str | None = None
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class MemoryProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    knowledge_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    why_this: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None


class MisconceptionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_ref: str
    label: str
    observed_pattern: str | None = None
    confidence: float | None = None
    supporting_evidence: list[str]
    recommended_repair_action: str | None = None


class ProgressProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_progress: dict[str, Any]
    learning_progress: dict[str, Any]
    evidence_mode: EvidenceMode


class SessionLearningSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    what_improved: list[str] = Field(default_factory=list)
    remains_uncertain: list[str] = Field(default_factory=list)
    what_is_fading: list[str] = Field(default_factory=list)
    misconception_detected_or_repaired: list[str] = Field(default_factory=list)
    what_comes_next: dict[str, Any] | None = None
    next_scheduled_review: datetime | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ReturnReasonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReturnReason
    knowledge_ref: str | None = None
    policy_decision_id: str | None = None
    measurement_schedule_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class NotificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    should_send: bool = False
    reason: NotificationReason | None = None
    knowledge_ref: str | None = None
    policy_decision_id: str | None = None
    measurement_schedule_id: str | None = None


class FlywheelHealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    n_interactions: int
    n_events: int
    n_usable_evidence: int
    event_coverage: float | None
    state_projection_coverage: float | None
    policy_trace_coverage: float | None
    outcome_linkage: float | None
    independent_evidence_rate: float | None
    delayed_evidence_rate: float | None
    contamination_rate: float | None
    model_evaluation_coverage: float | None
    usable_evidence_rate: float | None
    notes: list[str] = Field(default_factory=list)


class PolicyOutcomeLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    decision_id: UUID
    action_event_id: UUID
    outcome_event_id: UUID
    latency_seconds: float | None = Field(default=None, ge=0.0)
    eligible_for_evaluation: bool = False
    contamination_status: ContaminationStatus = ContaminationStatus.UNKNOWN
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_datetime(self) -> "PolicyOutcomeLink":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("policy outcome link timestamp must be timezone-aware")
        return self


class LearningOutcomeLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    decision_id: UUID
    action_event_id: UUID
    outcome_event_id: UUID
    knowledge_ref: str | None = None
    state_version: str | None = None
    policy_version: str | None = None
    outcome: dict[str, Any] = Field(default_factory=dict)
    evaluation_phase: str | None = None
    evaluation_kind: str = "descriptive"
    contamination_status: ContaminationStatus = ContaminationStatus.UNKNOWN
    protocol_id: str | None = None
    protocol_version: str | None = None
    occurred_at: datetime
    synthetic: bool = False


class ProductAnalyticsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    evidence_mode: EvidenceMode
    n_users: int
    n_events: int
    ttflv_seconds: float | None = None
    d1_return: float | None = None
    d7_return: float | None = None
    d30_return: float | None = None
    sessions_per_user: float | None = None
    learn_now_completion: float | None = None
    review_completion: float | None = None
    product_retention_note: str = PRODUCT_RETENTION_NOTE
    learning_outcomes: dict[str, Any] = Field(default_factory=dict)


class CohortAnalyticsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    evidence_mode: EvidenceMode
    cohort_basis: str
    n_users: int
    d1: float | None = None
    d7: float | None = None
    d30: float | None = None
    note: str = "NO REAL USER DATA"


class CommercialMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    evidence_mode: EvidenceMode
    activation: float | None = None
    free_to_pro_conversion: float | None = None
    trial_to_paid: float | None = None
    paid_retention: float | None = None
    mrr: float | None = None
    arpu: float | None = None
    churn: float | None = None


class ProductDashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductAnalyticsReport
    cohort: CohortAnalyticsReport
    flywheel: FlywheelHealthReport
    commercial: CommercialMetrics
    data_labels: list[EvidenceMode]


class SubscriptionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan = Plan.FREE
    status: SubscriptionStatus = SubscriptionStatus.NONE
    current_period_end: datetime | None = None
    synthetic: bool = False


class EntitlementView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan
    status: SubscriptionStatus
    capability: str
    allowed: bool
    reason: str


# Public domain names intentionally remain short for API/contract consumers;
# the ``View`` suffix is retained above to make their projection nature clear.
Subscription = SubscriptionView
Entitlement = EntitlementView


FREE_CAPABILITIES = frozenset({
    "learn_now",
    "basic_cognitive_state",
    "reviews",
    "basic_progress",
})
PRO_CAPABILITIES = frozenset({
    "advanced_analytics",
    "deep_evidence_history",
    "advanced_learning_reports",
    "longer_history",
    "advanced_export",
    "premium_ai_usage",
})


@runtime_checkable
class BillingProvider(Protocol):
    async def create_checkout(self, *, user_id: UUID, plan: Plan) -> dict[str, Any]: ...

    async def get_subscription(self, *, user_id: UUID) -> dict[str, Any]: ...

    async def cancel_subscription(self, *, user_id: UUID) -> dict[str, Any]: ...

    async def handle_webhook(self, *, payload: Mapping[str, Any], signature: str) -> dict[str, Any]: ...


class BillingProviderNotConfigured(RuntimeError):
    pass


class FakeBillingProvider:
    """Test-only billing adapter; construction is forbidden in production."""

    def __init__(self) -> None:
        if os.environ.get("MNEME_ENV", "dev").lower() in {"prod", "production"}:
            raise RuntimeError("FakeBillingProvider is forbidden in production")

    async def create_checkout(self, *, user_id: UUID, plan: Plan) -> dict[str, Any]:
        return {"status": "TEST_ONLY", "plan": plan.value, "synthetic": True}

    async def get_subscription(self, *, user_id: UUID) -> dict[str, Any]:
        return {"status": SubscriptionStatus.NONE.value, "synthetic": True}

    async def cancel_subscription(self, *, user_id: UUID) -> dict[str, Any]:
        return {"status": SubscriptionStatus.CANCELED.value, "synthetic": True}

    async def handle_webhook(self, *, payload: Mapping[str, Any], signature: str) -> dict[str, Any]:
        return {"status": "TEST_ONLY", "synthetic": True}


def get_billing_provider() -> BillingProvider:
    """Return no provider by default; never silently selects a real vendor."""

    if os.environ.get("BILLING_PROVIDER", "").strip():
        raise BillingProviderNotConfigured("BILLING_PROVIDER_NOT_CONFIGURED")
    raise BillingProviderNotConfigured("BILLING_PROVIDER_NOT_CONFIGURED")


def _value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _event_id(record: Any) -> str | None:
    value = _value(record, "event_id", _value(record, "id"))
    return str(value) if value is not None else None


def _student_id(record: Any) -> UUID | None:
    value = _value(record, "student_id")
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _occurred_at(record: Any) -> datetime | None:
    value = _value(record, "occurred_at")
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if isinstance(value, datetime) else None


def _metadata(record: Any) -> dict[str, Any]:
    provenance = _value(record, "provenance", {})
    metadata = _value(provenance, "metadata", {})
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def is_synthetic_event(record: Any) -> bool:
    from services.real_user_data import UserDataClass, classify_user_data

    return classify_user_data(record) != UserDataClass.REAL


def _action(record: Any) -> str:
    return str(_value(record, "action", ""))


def _knowledge_refs(record: Any) -> list[str]:
    values = _value(record, "knowledge_refs", None)
    if values is None:
        value = _value(record, "knowledge_ref", None)
        return [str(value)] if value else []
    return [str(value) for value in values if value]


def _outcome(record: Any) -> Mapping[str, Any]:
    value = _value(record, "outcome", {})
    if isinstance(value, Mapping):
        return value
    dumped = getattr(value, "model_dump", None)
    if callable(dumped):
        result = dumped()
        return result if isinstance(result, Mapping) else {}
    return {}


def _process_value(record: Any, name: str) -> float | None:
    process = _value(record, "process_signals", {})
    value = _value(process, name)
    if value is None:
        value = _metadata(record).get(name)
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_key(record: Any) -> tuple[datetime, str]:
    occurred = _occurred_at(record) or datetime.min.replace(tzinfo=UTC)
    return occurred, _event_id(record) or ""


def create_product_learning_event(
    *,
    student_id: UUID,
    event_type: ProductEventType | str,
    occurred_at: datetime,
    session_id: UUID | None = None,
    knowledge_refs: Sequence[str] = (),
    policy_decision_id: UUID | None = None,
    outcome: EventOutcome | None = None,
    trace_id: str | None = None,
    synthetic: bool = False,
) -> LearningEvent:
    """Create a product interaction as a normal LearningEvent v2 fact."""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("product event timestamp must be timezone-aware")
    action = event_type.value if isinstance(event_type, ProductEventType) else str(event_type)
    if action not in {item.value for item in ProductEventType}:
        raise ValueError(f"unknown product event type: {action}")
    metadata: dict[str, Any] = {"product_event": action}
    if policy_decision_id is not None:
        metadata["policy_decision_id"] = str(policy_decision_id)
    if synthetic:
        metadata["synthetic"] = True
    return LearningEvent(
        student_id=student_id,
        actor_id=student_id,
        session_id=session_id,
        occurred_at=occurred_at,
        source="product",
        action=action,
        object_type="product_surface",
        object_id=action,
        knowledge_refs=list(knowledge_refs),
        outcome=outcome,
        provenance=EventProvenance(
            adapter="product_closure/v1",
            source_system="services.product_closure",
            metadata=metadata,
        ),
        trace_id=trace_id,
    )


async def append_product_learning_event(db: Any, event: LearningEvent) -> Any:
    """Append through the existing LearningEvent v2 persistence boundary."""

    from services.learning_event_service import append_learning_event

    return await append_learning_event(db, event)


def advance_first_value_state(
    events: Iterable[Any],
    *,
    state: FirstValueState | None = None,
    cognitive_state_available: bool = False,
    policy_decision_available: bool = False,
) -> FirstValueState:
    """Reduce first-value progress from real, non-synthetic events only."""

    current = state or FirstValueState()
    if current.stage == FirstValueStage.FIRST_VALUE_COMPLETE:
        return current
    real_events = sorted(
        [event for event in events if _student_id(event) is not None and not is_synthetic_event(event)],
        key=_event_key,
    )
    if not real_events:
        return current
    start_candidates = [
        _occurred_at(event)
        for event in real_events
        if _action(event)
        in {ProductEventType.CONTENT_READY.value, ProductEventType.LEARNING_SESSION_STARTED.value}
    ]
    started_at = current.started_at or min(
        (value for value in start_candidates if value is not None),
        default=_occurred_at(real_events[0]),
    )
    has_content = any(
        _action(event)
        in {ProductEventType.CONTENT_READY.value, ProductEventType.LEARNING_SESSION_STARTED.value}
        for event in real_events
    )
    has_attempt = any(
        _action(event) in {"attempted", "answered", "submitted"} or bool(_outcome(event))
        for event in real_events
    )
    stage = FirstValueStage.NEW
    if has_content:
        stage = FirstValueStage.CONTENT_READY
    if has_attempt:
        stage = FirstValueStage.FIRST_ATTEMPT
    if has_attempt and cognitive_state_available:
        stage = FirstValueStage.FIRST_STATE
    if has_attempt and cognitive_state_available and policy_decision_available:
        stage = FirstValueStage.FIRST_RECOMMENDATION
        stage = FirstValueStage.FIRST_VALUE_COMPLETE
    completed_at = current.completed_at
    if stage == FirstValueStage.FIRST_VALUE_COMPLETE and completed_at is None:
        completed_at = _occurred_at(real_events[-1])
    elapsed = None
    if started_at is not None and completed_at is not None:
        elapsed = max(0.0, (completed_at - started_at).total_seconds())
    return FirstValueState(
        stage=stage,
        started_at=started_at,
        completed_at=completed_at,
        time_to_first_value_seconds=elapsed,
    )


def time_to_first_value_seconds(state: FirstValueState) -> float | None:
    return state.time_to_first_value_seconds if state.stage == FirstValueStage.FIRST_VALUE_COMPLETE else None


def compute_first_value(
    events: Iterable[Any],
    *,
    cognitive_state_available: bool = False,
    policy_decision_available: bool = False,
    state: FirstValueState | None = None,
) -> FirstValueState:
    """Named product API for the resumable first-value reducer."""

    return advance_first_value_state(
        events,
        state=state,
        cognitive_state_available=cognitive_state_available,
        policy_decision_available=policy_decision_available,
    )


def build_learn_now(
    policy_decision: Any | None,
    evidence_claims: Iterable[Any] = (),
) -> LearnNowView:
    """Build Learn Now from a real PolicyDecision and its evidence references."""

    if policy_decision is None:
        return LearnNowView(status="NO_DATA")
    dumped = policy_decision.model_dump(mode="json") if hasattr(policy_decision, "model_dump") else dict(policy_decision)
    selected = dumped.get("selected_action")
    decision_id = dumped.get("decision_id")
    refs = [str(ref) for ref in dumped.get("evidence_refs", [])]
    why: list[dict[str, Any]] = []
    for claim in evidence_claims:
        item = claim.model_dump(mode="json") if hasattr(claim, "model_dump") else dict(claim)
        claim_refs = {str(ref) for ref in item.get("evidence_refs", item.get("provenance", {}).get("evidence_refs", []))}
        if claim_refs.intersection(refs):
            why.append({
                "claim_type": item.get("claim_type"),
                "claim_value": item.get("claim_value"),
                "evidence_refs": sorted(claim_refs),
            })
    if selected is None:
        return LearnNowView(
            status="CAUGHT_UP",
            policy_decision_id=str(decision_id) if decision_id else None,
            reason_codes=[str(value) for value in dumped.get("reason_codes", [])],
            evidence_refs=refs,
            why_this=why,
        )
    return LearnNowView(
        status="READY",
        selected_action=selected,
        policy_decision_id=str(decision_id) if decision_id else None,
        reason_codes=[str(value) for value in dumped.get("reason_codes", [])],
        evidence_refs=refs,
        why_this=why,
    )


def build_today_queue(tasks: Iterable[Mapping[str, Any]], policy_decision: Any | None) -> TodayQueue:
    """Use the existing policy ranking; this function never ranks tasks itself."""

    rows = [dict(task) for task in tasks]
    if not rows:
        return TodayQueue(status="CAUGHT_UP", message="You're caught up")
    if policy_decision is None:
        return TodayQueue(status="POLICY_REQUIRED", message="Policy decision required")
    dumped = policy_decision.model_dump(mode="json") if hasattr(policy_decision, "model_dump") else dict(policy_decision)
    ordered_ids = [
        str(value.get("candidate_id")) if isinstance(value, Mapping) else str(value)
        for value in dumped.get("candidate_actions", [])
    ]
    by_id = {str(row.get("candidate_id")): row for row in rows if row.get("candidate_id") is not None}
    ordered = [by_id[item] for item in ordered_ids if item in by_id]
    ordered.extend(row for row in rows if row not in ordered)
    return TodayQueue(
        status="READY",
        policy_decision_id=str(dumped.get("decision_id")) if dumped.get("decision_id") else None,
        tasks=ordered,
    )


def _state_value(state: Any, name: str, default: Any = None) -> Any:
    return _value(state, name, default)


def memory_label(state: Any) -> str:
    """Map CognitiveState fields to a human label without exposing precision."""

    mastery = _state_value(state, "mastery_probability")
    confidence = _state_value(state, "mastery_confidence")
    sufficiency = _state_value(state, "evidence_sufficiency")
    uncertainty = _state_value(state, "epistemic_uncertainty")
    retrievability = _state_value(state, "retrievability")
    forgetting_risk = _state_value(state, "forgetting_risk")
    if mastery is None:
        return "Unknown"
    if (
        _state_value(state, "stale", False)
        or _state_value(state, "out_of_distribution", False)
        or confidence is None
        or (uncertainty is not None and float(uncertainty) >= MEMORY_LABEL_THRESHOLDS["high_uncertainty"])
        or (sufficiency is not None and float(sufficiency) < MEMORY_LABEL_THRESHOLDS["sufficient_evidence"])
    ):
        return "Unknown"
    if (
        (retrievability is not None and float(retrievability) < MEMORY_LABEL_THRESHOLDS["fading_retrievability"])
        or (forgetting_risk is not None and float(forgetting_risk) >= 0.60)
    ):
        return "Fading"
    if float(mastery) >= MEMORY_LABEL_THRESHOLDS["strong_mastery"]:
        return "Strong"
    return "Learning"


def project_memory(state: Any, *, knowledge_ref: str | None = None, advanced: bool = False) -> MemoryProjection:
    refs = [str(ref) for ref in _value(state, "evidence_event_ids", _value(state, "evidence_refs", []))]
    label = memory_label(state)
    details = None
    if advanced:
        details = {
            "mastery_probability": _state_value(state, "mastery_probability"),
            "mastery_confidence": _state_value(state, "mastery_confidence"),
            "retrievability": _state_value(state, "retrievability"),
            "epistemic_uncertainty": _state_value(state, "epistemic_uncertainty"),
            "evidence_sufficiency": _state_value(state, "evidence_sufficiency"),
        }
    why = ["state_projection", "evidence_backed"] if refs else ["insufficient_evidence"]
    return MemoryProjection(label=label, knowledge_ref=knowledge_ref, evidence_refs=refs, why_this=why, details=details)


def project_misconceptions(claims: Iterable[Any]) -> list[MisconceptionProjection]:
    result: list[MisconceptionProjection] = []
    for claim in claims:
        item = claim.model_dump(mode="json") if hasattr(claim, "model_dump") else dict(claim)
        claim_type = str(item.get("claim_type", ""))
        refs = [str(ref) for ref in item.get("evidence_refs", item.get("provenance", {}).get("evidence_refs", [])) if ref]
        knowledge_ref = item.get("knowledge_ref") or item.get("subject_id")
        if claim_type not in {"misconception", "misconception_detected", "misconception_repair"} or not knowledge_ref or not refs:
            continue
        confidence = item.get("confidence", item.get("uncertainty", {}).get("confidence"))
        label = "Misconception" if confidence is not None and float(confidence) >= 0.70 else "Possible misconception"
        value = item.get("claim_value") or {}
        if not isinstance(value, Mapping):
            value = {}
        result.append(MisconceptionProjection(
            knowledge_ref=str(knowledge_ref),
            label=label,
            observed_pattern=value.get("pattern") or value.get("observed_pattern"),
            confidence=float(confidence) if confidence is not None else None,
            supporting_evidence=refs,
            recommended_repair_action=value.get("recommended_repair_action") or "diagnostic_repair",
        ))
    return result


def _event_is_attempt(record: Any) -> bool:
    return _action(record) in {"attempted", "answered", "submitted"} or bool(_outcome(record))


def project_progress(
    activity_events: Iterable[Any],
    learning_outcomes: Mapping[str, Any] | None = None,
) -> ProgressProjection:
    events = [event for event in activity_events if not is_synthetic_event(event)]
    active_seconds = sum(_process_value(event, "active_learning_seconds") or 0.0 for event in events)
    attempts = sum(1 for event in events if _event_is_attempt(event))
    reviews = sum(1 for event in events if _action(event) == ProductEventType.REVIEW_COMPLETED.value)
    days = len({value.date() for event in events if (value := _occurred_at(event)) is not None})
    outcomes = dict(learning_outcomes or {})
    has_delayed = any(outcomes.get(key) is not None for key in ("retention_7d", "retention_30d"))
    learning = {
        "retained_mastery": outcomes.get("retained_mastery"),
        "retention": outcomes.get("retention"),
        "transfer": outcomes.get("transfer"),
        "independent_performance": outcomes.get("independent_performance"),
        "jol_calibration": outcomes.get("jol_calibration"),
        "long_term_retention_label": "Measured" if has_delayed else "Long-term retention not measured yet.",
    }
    mode = EvidenceMode.REAL if events or outcomes else EvidenceMode.NO_DATA
    return ProgressProjection(
        activity_progress={
            "active_minutes": round(active_seconds / 60.0, 4) if events and active_seconds > 0 else None,
            "attempts": attempts if events else None,
            "reviews": reviews if events else None,
            "learning_days": days if events else None,
        },
        learning_progress=learning,
        evidence_mode=mode,
    )


def build_session_summary(
    events: Iterable[Any],
    *,
    cognitive_state: Any | None = None,
    policy_decision: Any | None = None,
    misconception_claims: Iterable[Any] = (),
    next_scheduled_review: datetime | None = None,
) -> SessionLearningSummary:
    rows = [event for event in events if not is_synthetic_event(event)]
    refs = [_event_id(event) for event in rows if _event_id(event)]
    improved = ["successful response observed"] if any(bool(_outcome(event).get("correctness")) for event in rows) else []
    uncertain = []
    if cognitive_state is not None:
        if memory_label(cognitive_state) == "Unknown":
            uncertain.append("evidence is still uncertain")
        if memory_label(cognitive_state) == "Fading":
            uncertain.append("retrievability is fading")
    misconceptions = project_misconceptions(misconception_claims)
    fading = ["retrievability is fading"] if cognitive_state is not None and memory_label(cognitive_state) == "Fading" else []
    next_action = None
    if policy_decision is not None:
        dumped = policy_decision.model_dump(mode="json") if hasattr(policy_decision, "model_dump") else dict(policy_decision)
        next_action = dumped.get("selected_action")
    return SessionLearningSummary(
        session_id=str(_value(rows[0], "session_id")) if rows and _value(rows[0], "session_id") else None,
        what_improved=improved,
        remains_uncertain=uncertain,
        what_is_fading=fading,
        misconception_detected_or_repaired=[item.knowledge_ref for item in misconceptions],
        what_comes_next=next_action,
        next_scheduled_review=next_scheduled_review,
        evidence_refs=[str(ref) for ref in refs],
    )


def get_return_reason(
    student: Any = None,
    *,
    events: Iterable[Any] | None = None,
    cognitive_state: Any | None = None,
    schedules: Iterable[Any] = (),
    now: datetime | None = None,
) -> ReturnReasonResult:
    """Return a real reason to reopen; no rows means NONE."""

    if isinstance(student, Mapping):
        events = events if events is not None else student.get("events", [])
        cognitive_state = cognitive_state if cognitive_state is not None else student.get("cognitive_state")
        schedules = student.get("schedules", schedules)
    rows = [event for event in (events or []) if not is_synthetic_event(event)]
    current = now or datetime.now(UTC)
    for schedule in sorted(schedules, key=lambda item: str(_value(item, "measurement_due_at", ""))):
        status = str(_value(schedule, "status", ""))
        due = _value(schedule, "measurement_due_at")
        if status in {"AVAILABLE", "SCHEDULED"} and isinstance(due, datetime) and due <= current:
            phase = str(_value(schedule, "phase", ""))
            return ReturnReasonResult(
                reason=ReturnReason.DELAYED_TEST_DUE if phase.startswith("delayed") else ReturnReason.REVIEW_DUE,
                measurement_schedule_id=str(_value(schedule, "schedule_id")) if _value(schedule, "schedule_id") else None,
            )
    if cognitive_state is not None and memory_label(cognitive_state) == "Fading":
        return ReturnReasonResult(reason=ReturnReason.MEMORY_FADING)
    if rows:
        latest = max(rows, key=_event_key)
        metadata = _metadata(latest)
        latest_refs = _knowledge_refs(latest)
        if metadata.get("misconception_repair_due"):
            return ReturnReasonResult(reason=ReturnReason.MISCONCEPTION_REPAIR, knowledge_ref=latest_refs[0] if latest_refs else None)
        if metadata.get("transfer_check_due"):
            return ReturnReasonResult(reason=ReturnReason.TRANSFER_CHECK, knowledge_ref=latest_refs[0] if latest_refs else None)
        if _action(latest) == ProductEventType.LEARNING_SESSION_STARTED.value:
            return ReturnReasonResult(reason=ReturnReason.CONTINUE_LEARNING)
    return ReturnReasonResult(reason=ReturnReason.NONE)


def build_notification_contract(
    reason: ReturnReasonResult,
    *,
    notifications_enabled: bool = False,
    policy_decision_id: str | None = None,
) -> NotificationContract:
    mapping = {
        ReturnReason.REVIEW_DUE: NotificationReason.REVIEW_DUE,
        ReturnReason.MEMORY_FADING: NotificationReason.MEMORY_FADING,
        ReturnReason.DELAYED_TEST_DUE: NotificationReason.DELAYED_TEST_DUE,
    }
    notification_reason = mapping.get(reason.reason)
    return NotificationContract(
        enabled=notifications_enabled,
        should_send=notifications_enabled and notification_reason is not None and reason.reason != ReturnReason.NONE,
        reason=notification_reason,
        knowledge_ref=reason.knowledge_ref,
        policy_decision_id=policy_decision_id or reason.policy_decision_id,
        measurement_schedule_id=reason.measurement_schedule_id,
    )


def _contamination(record: Any) -> ContaminationStatus:
    raw = _metadata(record).get("contamination_status") or _value(record, "contamination_status")
    try:
        return ContaminationStatus(str(_scalar(raw))) if raw is not None else ContaminationStatus.CLEAN
    except ValueError:
        return ContaminationStatus.UNKNOWN


def _is_usable_event(record: Any) -> bool:
    if is_synthetic_event(record) or _student_id(record) is None or not _knowledge_refs(record):
        return False
    if not _outcome(record):
        return False
    return _contamination(record) == ContaminationStatus.CLEAN


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator > 0 else None


def compute_flywheel_health(
    *,
    interactions: Iterable[Any],
    events: Iterable[Any],
    states: Iterable[Any] = (),
    policy_decisions: Iterable[Any] = (),
    outcome_links: Iterable[Any] = (),
    model_evaluations: Iterable[Any] = (),
) -> FlywheelHealthReport:
    interaction_rows = [row for row in interactions if not is_synthetic_event(row)]
    event_rows = [row for row in events if not is_synthetic_event(row)]
    usable = [row for row in event_rows if _is_usable_event(row)]
    state_rows = list(states)
    decisions = list(policy_decisions)
    links = list(outcome_links)
    evals = list(model_evaluations)
    evaluation_rows = [row for row in event_rows if _value(row, "evaluation_phase")]
    independent = [row for row in evaluation_rows if str(_value(row, "evaluation_phase")) == "independent_no_ai"]
    delayed = [row for row in evaluation_rows if str(_value(row, "evaluation_phase")).startswith("delayed")]
    contaminated = [row for row in evaluation_rows if _contamination(row) != ContaminationStatus.CLEAN]
    state_covered = sum(1 for state in state_rows if _value(state, "evidence_refs", _value(state, "evidence_event_ids", [])))
    decision_covered = sum(1 for decision in decisions if _value(decision, "evidence_refs", []))
    linked = sum(1 for link in links if bool(_value(link, "eligible_for_evaluation", False)))
    denominator = len(interaction_rows)
    status = "NO_DATA" if denominator == 0 else "READY"
    return FlywheelHealthReport(
        status=status,
        n_interactions=denominator,
        n_events=len(event_rows),
        n_usable_evidence=len(usable),
        event_coverage=_rate(len(event_rows), denominator),
        state_projection_coverage=_rate(state_covered, len(usable)),
        policy_trace_coverage=_rate(decision_covered, len(state_rows) or len(usable)),
        outcome_linkage=_rate(linked, len(decisions)),
        independent_evidence_rate=_rate(len(independent), len(evaluation_rows)),
        delayed_evidence_rate=_rate(len(delayed), len(evaluation_rows)),
        contamination_rate=_rate(len(contaminated), len(evaluation_rows)),
        model_evaluation_coverage=_rate(len(evals), len(usable)),
        usable_evidence_rate=_rate(len(usable), denominator),
        notes=["usable_evidence_rate counts evidence-bearing real events, not raw event volume."]
        if denominator
        else ["NO REAL USER DATA"],
    )


def link_policy_outcome(
    *,
    decision: Any,
    action_event: Any,
    outcome_event: Any,
    contamination_status: ContaminationStatus = ContaminationStatus.UNKNOWN,
    eligible_for_evaluation: bool = False,
) -> PolicyOutcomeLink:
    decision_id = _value(decision, "decision_id")
    action_id = _value(action_event, "event_id", _value(action_event, "id"))
    outcome_id = _value(outcome_event, "event_id", _value(outcome_event, "id"))
    student_id = _student_id(outcome_event) or _student_id(action_event) or _value(decision, "student_id")
    if not all((decision_id, action_id, outcome_id, student_id)):
        raise ValueError("policy outcome link requires decision, action, outcome and student identifiers")
    action_at = _occurred_at(action_event)
    outcome_at = _occurred_at(outcome_event)
    latency = None
    if action_at and outcome_at:
        latency = max(0.0, (outcome_at - action_at).total_seconds())
    return PolicyOutcomeLink(
        student_id=student_id if isinstance(student_id, UUID) else UUID(str(student_id)),
        decision_id=decision_id if isinstance(decision_id, UUID) else UUID(str(decision_id)),
        action_event_id=action_id if isinstance(action_id, UUID) else UUID(str(action_id)),
        outcome_event_id=outcome_id if isinstance(outcome_id, UUID) else UUID(str(outcome_id)),
        latency_seconds=latency,
        eligible_for_evaluation=eligible_for_evaluation,
        contamination_status=contamination_status,
        trace_id=_value(decision, "trace_id") or _value(outcome_event, "trace_id"),
    )


def project_outcome_ledger(
    *,
    decisions: Iterable[Any],
    action_events: Iterable[Any],
    outcome_events: Iterable[Any],
    links: Iterable[PolicyOutcomeLink | Mapping[str, Any]],
) -> list[LearningOutcomeLedgerEntry]:
    decisions_by_id = {str(_value(row, "decision_id")): row for row in decisions}
    actions_by_id = {_event_id(row): row for row in action_events if _event_id(row)}
    outcomes_by_id = {_event_id(row): row for row in outcome_events if _event_id(row)}
    result: list[LearningOutcomeLedgerEntry] = []
    for link in links:
        decision = decisions_by_id.get(str(_value(link, "decision_id")))
        action = actions_by_id.get(str(_value(link, "action_event_id")))
        outcome = outcomes_by_id.get(str(_value(link, "outcome_event_id")))
        outcome_student = _student_id(outcome) if outcome is not None else None
        outcome_at = _occurred_at(outcome) if outcome is not None else None
        if decision is None or action is None or outcome is None or outcome_student is None or outcome_at is None:
            continue
        phase = _value(outcome, "evaluation_phase")
        knowledge = _knowledge_refs(outcome) or _knowledge_refs(action)
        result.append(LearningOutcomeLedgerEntry(
            student_id=outcome_student,
            decision_id=UUID(str(_value(link, "decision_id"))),
            action_event_id=UUID(str(_value(link, "action_event_id"))),
            outcome_event_id=UUID(str(_value(link, "outcome_event_id"))),
            knowledge_ref=knowledge[0] if knowledge else None,
            state_version=_value(decision, "state_version"),
            policy_version=_value(decision, "policy_version"),
            outcome=dict(_outcome(outcome)),
            evaluation_phase=str(phase) if phase else None,
            evaluation_kind="randomized" if _value(outcome, "protocol_id") and _value(outcome, "assignment_method") else "observational",
            contamination_status=ContaminationStatus(str(_scalar(_value(link, "contamination_status", "UNKNOWN")))),
            protocol_id=_value(outcome, "protocol_id"),
            protocol_version=_value(outcome, "protocol_version"),
            occurred_at=outcome_at,
            synthetic=is_synthetic_event(outcome),
        ))
    return result


async def persist_policy_outcome_link(db: Any, link: PolicyOutcomeLink) -> Any:
    """Persist only the attribution edge; callers own commit/authorization."""

    from sqlalchemy import select

    from services.models import PolicyOutcomeLinkRecord

    existing = (
        await db.execute(
            select(PolicyOutcomeLinkRecord).where(
                PolicyOutcomeLinkRecord.decision_id == link.decision_id,
                PolicyOutcomeLinkRecord.action_event_id == link.action_event_id,
                PolicyOutcomeLinkRecord.outcome_event_id == link.outcome_event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = PolicyOutcomeLinkRecord(
        link_id=link.link_id,
        student_id=link.student_id,
        decision_id=link.decision_id,
        action_event_id=link.action_event_id,
        outcome_event_id=link.outcome_event_id,
        latency_seconds=link.latency_seconds,
        eligible_for_evaluation=link.eligible_for_evaluation,
        contamination_status=link.contamination_status.value,
        trace_id=link.trace_id,
        created_at=link.created_at,
    )
    db.add(row)
    await db.flush()
    return row


async def persist_outcome_ledger_entry(db: Any, entry: LearningOutcomeLedgerEntry) -> Any:
    """Persist a projection row; raw LearningEvent remains the fact source."""

    from sqlalchemy import select

    from services.models import LearningOutcomeLedgerRecord

    existing = (
        await db.execute(
            select(LearningOutcomeLedgerRecord).where(
                LearningOutcomeLedgerRecord.decision_id == entry.decision_id,
                LearningOutcomeLedgerRecord.action_event_id == entry.action_event_id,
                LearningOutcomeLedgerRecord.outcome_event_id == entry.outcome_event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = LearningOutcomeLedgerRecord(
        ledger_id=entry.ledger_id,
        student_id=entry.student_id,
        decision_id=entry.decision_id,
        action_event_id=entry.action_event_id,
        outcome_event_id=entry.outcome_event_id,
        knowledge_ref=entry.knowledge_ref,
        state_version=entry.state_version,
        policy_version=entry.policy_version,
        outcome=entry.outcome,
        evaluation_phase=entry.evaluation_phase,
        evaluation_kind=entry.evaluation_kind,
        contamination_status=entry.contamination_status.value,
        protocol_id=entry.protocol_id,
        protocol_version=entry.protocol_version,
        occurred_at=entry.occurred_at,
        synthetic=entry.synthetic,
    )
    db.add(row)
    await db.flush()
    return row


def build_candidate_evaluation_dataset(
    entries: Iterable[LearningOutcomeLedgerEntry | Mapping[str, Any]],
    *,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    heldout_students: set[UUID] | None = None,
) -> list[LearningOutcomeLedgerEntry | Mapping[str, Any]]:
    """Filter a candidate set; output is shadow-only and never promotes a model."""

    if train_end > eval_start or eval_start >= eval_end:
        raise ValueError("evaluation windows must be ordered")
    selected: list[LearningOutcomeLedgerEntry | Mapping[str, Any]] = []
    for entry in entries:
        occurred = _occurred_at(entry)
        student = _student_id(entry)
        contamination = str(_scalar(_value(entry, "contamination_status", "UNKNOWN")))
        if occurred is None or student is None or not eval_start <= occurred < eval_end:
            continue
        if heldout_students is not None and student not in heldout_students:
            continue
        if contamination != ContaminationStatus.CLEAN.value or is_synthetic_event(entry):
            continue
        selected.append(entry)
    return selected


def shadow_feedback_contract(entries: Sequence[Any]) -> dict[str, Any]:
    return {
        "mode": "shadow_only",
        "candidate_n": len(entries),
        "controls_learning_path": False,
        "writes_database": False,
        "auto_promote": False,
        "promotion_requires_model_registry": True,
    }


def _first_value_times(events: Sequence[Any]) -> dict[UUID, tuple[datetime, datetime]]:
    by_user: dict[UUID, list[Any]] = defaultdict(list)
    for event in events:
        student = _student_id(event)
        if student is not None and not is_synthetic_event(event):
            by_user[student].append(event)
    result: dict[UUID, tuple[datetime, datetime]] = {}
    for student, rows in by_user.items():
        ordered = sorted(rows, key=_event_key)
        started = next((_occurred_at(row) for row in ordered if _action(row) in {ProductEventType.CONTENT_READY.value, ProductEventType.LEARNING_SESSION_STARTED.value}), None)
        completed = next((_occurred_at(row) for row in ordered if _action(row) == ProductEventType.FIRST_VALUE_COMPLETED.value), None)
        if started and completed and completed >= started:
            result[student] = (started, completed)
    return result


def _return_rate(events: Sequence[Any], days: int) -> float | None:
    by_user: dict[UUID, list[datetime]] = defaultdict(list)
    for event in events:
        student = _student_id(event)
        occurred = _occurred_at(event)
        if student and occurred and not is_synthetic_event(event):
            by_user[student].append(occurred)
    eligible: list[bool] = []
    for timestamps in by_user.values():
        first = min(timestamps)
        target = first + timedelta(days=days)
        if max(timestamps) < target:
            continue
        eligible.append(any(target <= stamp < target + timedelta(days=1) for stamp in timestamps))
    return _rate(sum(eligible), len(eligible))


def compute_product_analytics(events: Iterable[Any], *, now: datetime | None = None, learning_outcomes: Mapping[str, Any] | None = None) -> ProductAnalyticsReport:
    rows = [event for event in events if not is_synthetic_event(event)]
    users = {_student_id(row) for row in rows if _student_id(row) is not None}
    if not rows or not users:
        return ProductAnalyticsReport(status="NO REAL USER DATA", evidence_mode=EvidenceMode.NO_DATA, n_users=0, n_events=0, learning_outcomes=dict(learning_outcomes or {}))
    first_values = _first_value_times(rows)
    ttflv = sum((end - start).total_seconds() for start, end in first_values.values()) / len(first_values) if first_values else None
    starts = sum(1 for row in rows if _action(row) == ProductEventType.LEARNING_SESSION_STARTED.value)
    completions = sum(1 for row in rows if _action(row) == ProductEventType.LEARNING_SESSION_COMPLETED.value)
    reviews = sum(1 for row in rows if _action(row) == ProductEventType.REVIEW_COMPLETED.value)
    product_learning_outcomes = dict(learning_outcomes or {})
    return ProductAnalyticsReport(
        status="READY",
        evidence_mode=EvidenceMode.REAL,
        n_users=len(users),
        n_events=len(rows),
        ttflv_seconds=round(ttflv, 4) if ttflv is not None else None,
        d1_return=_return_rate(rows, 1),
        d7_return=_return_rate(rows, 7),
        d30_return=_return_rate(rows, 30),
        sessions_per_user=round(starts / len(users), 6),
        learn_now_completion=_rate(completions, starts),
        review_completion=_rate(reviews, sum(1 for row in rows if _action(row) == ProductEventType.NEXT_BEST_ACTION_STARTED.value)),
        learning_outcomes=product_learning_outcomes,
    )


def compute_cohort_analytics(events: Iterable[Any], *, cohort_basis: str = "signup") -> CohortAnalyticsReport:
    rows = [event for event in events if not is_synthetic_event(event)]
    users = {_student_id(row) for row in rows if _student_id(row) is not None}
    if not users:
        return CohortAnalyticsReport(status="NO REAL USER DATA", evidence_mode=EvidenceMode.NO_DATA, cohort_basis=cohort_basis, n_users=0)
    return CohortAnalyticsReport(status="READY", evidence_mode=EvidenceMode.REAL, cohort_basis=cohort_basis, n_users=len(users), d1=_return_rate(rows, 1), d7=_return_rate(rows, 7), d30=_return_rate(rows, 30), note="PRODUCT RETENTION; not learning retention")


def compute_commercial_metrics(records: Iterable[Any] = ()) -> CommercialMetrics:
    rows = [record for record in records if not bool(_value(record, "synthetic", False))]
    if not rows:
        return CommercialMetrics(status="NO COMMERCIAL EVIDENCE", evidence_mode=EvidenceMode.NO_DATA)
    return CommercialMetrics(status="READY", evidence_mode=EvidenceMode.REAL)


def _subscription_view(user: Any) -> SubscriptionView:
    raw = _value(user, "subscription", user)
    if isinstance(raw, SubscriptionView):
        return raw
    data = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw) if isinstance(raw, Mapping) else {}
    try:
        plan = Plan(str(data.get("plan", Plan.FREE.value)))
    except ValueError:
        plan = Plan.FREE
    try:
        status = SubscriptionStatus(str(data.get("status", SubscriptionStatus.NONE.value)))
    except ValueError:
        status = SubscriptionStatus.NONE
    period_end = data.get("current_period_end")
    if isinstance(period_end, str):
        period_end = datetime.fromisoformat(period_end)
    return SubscriptionView(plan=plan, status=status, current_period_end=period_end, synthetic=bool(data.get("synthetic", False)))


def check_entitlement(user: Any, capability: str, *, now: datetime | None = None) -> EntitlementView:
    """Server-side entitlement check; unknown capabilities and states fail closed."""

    sub = _subscription_view(user)
    current = now or datetime.now(UTC)
    active = sub.status in {SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE}
    if sub.current_period_end is not None and sub.current_period_end <= current:
        active = False
    if capability in FREE_CAPABILITIES:
        allowed = True
        reason = "free_core_capability"
    elif capability in PRO_CAPABILITIES:
        allowed = sub.plan == Plan.PRO and active and not sub.synthetic
        reason = "active_pro" if allowed else "pro_entitlement_required"
    else:
        allowed = False
        reason = "unknown_capability"
    return EntitlementView(plan=sub.plan, status=sub.status, capability=capability, allowed=allowed, reason=reason)


def require_entitlement(user: Any, capability: str, *, now: datetime | None = None) -> EntitlementView:
    result = check_entitlement(user, capability, now=now)
    if not result.allowed:
        raise PermissionError(result.reason)
    return result


def product_dashboard(
    *,
    product: ProductAnalyticsReport,
    cohort: CohortAnalyticsReport,
    flywheel: FlywheelHealthReport,
    commercial: CommercialMetrics,
) -> ProductDashboard:
    return ProductDashboard(product=product, cohort=cohort, flywheel=flywheel, commercial=commercial, data_labels=[product.evidence_mode, cohort.evidence_mode, flywheel_status_mode(flywheel), commercial.evidence_mode])


def flywheel_status_mode(report: FlywheelHealthReport) -> EvidenceMode:
    return EvidenceMode.NO_DATA if report.status == "NO_DATA" else EvidenceMode.REAL


def claim_guard_product(claim: str, *, evidence_mode: EvidenceMode = EvidenceMode.NO_DATA) -> dict[str, Any]:
    lowered = claim.lower()
    causal = any(token in lowered for token in ("improves learning", "learning effect", "提高学习", "提升学习效果", "product-market fit"))
    # Real product usage is not causal learning evidence. A future randomized
    # report must pass the existing PilotProtocol/claim guard before a causal
    # statement can be released.
    allowed = not causal
    return {"allowed": allowed, "claim": claim, "evidence_mode": evidence_mode.value, "reason": "evidence_required" if not allowed else "within_evidence_boundary"}


# Stable names for service/contract consumers; all aliases resolve to the same
# implementation so the repository does not grow parallel product systems.
LearningOutcomeLedger = LearningOutcomeLedgerEntry
learn_now = build_learn_now
today_queue = build_today_queue
memory_projection = project_memory
misconception_projection = project_misconceptions
session_learning_summary = build_session_summary
return_reason = get_return_reason
product_analytics = compute_product_analytics
cohort_analytics = compute_cohort_analytics
commercial_metrics = compute_commercial_metrics
flywheel_health_report = compute_flywheel_health


__all__ = [
    "BillingProvider",
    "BillingProviderNotConfigured",
    "CohortAnalyticsReport",
    "CommercialMetrics",
    "ContaminationStatus",
    "EntitlementView",
    "Entitlement",
    "EvidenceMode",
    "FakeBillingProvider",
    "FirstValueStage",
    "FirstValueState",
    "FlywheelHealthReport",
    "FREE_CAPABILITIES",
    "LearnNowView",
    "LearningOutcomeLedgerEntry",
    "LearningOutcomeLedger",
    "MemoryProjection",
    "MisconceptionProjection",
    "NotificationContract",
    "NotificationReason",
    "Plan",
    "PolicyOutcomeLink",
    "ProductAnalyticsReport",
    "ProductDashboard",
    "ProductEventType",
    "ProgressProjection",
    "PRO_CAPABILITIES",
    "ReturnReason",
    "ReturnReasonResult",
    "SessionLearningSummary",
    "SubscriptionStatus",
    "Subscription",
    "TodayQueue",
    "advance_first_value_state",
    "append_product_learning_event",
    "build_candidate_evaluation_dataset",
    "build_learn_now",
    "build_notification_contract",
    "build_session_summary",
    "build_today_queue",
    "check_entitlement",
    "claim_guard_product",
    "compute_cohort_analytics",
    "compute_commercial_metrics",
    "compute_first_value",
    "compute_flywheel_health",
    "compute_product_analytics",
    "create_product_learning_event",
    "get_billing_provider",
    "get_return_reason",
    "is_synthetic_event",
    "link_policy_outcome",
    "learn_now",
    "memory_projection",
    "misconception_projection",
    "memory_label",
    "product_dashboard",
    "project_memory",
    "project_misconceptions",
    "project_outcome_ledger",
    "project_progress",
    "product_analytics",
    "cohort_analytics",
    "commercial_metrics",
    "flywheel_health_report",
    "persist_outcome_ledger_entry",
    "persist_policy_outcome_link",
    "require_entitlement",
    "return_reason",
    "session_learning_summary",
    "shadow_feedback_contract",
    "time_to_first_value_seconds",
    "today_queue",
]

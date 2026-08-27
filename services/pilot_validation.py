"""Real-world validation contracts built on the existing Evaluation OS.

This module is deliberately conservative.  It classifies evidence once,
calculates only explicitly supported endpoints, and returns null/status values
when a real observation, window, or activity measure is missing.  It never
creates synthetic observations and it never changes learner state.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PilotStage(str, Enum):
    baseline = "baseline"
    practice = "practice"
    immediate_test = "immediate_test"
    delayed_7d = "delayed_7d"
    delayed_30d = "delayed_30d"
    near_transfer = "near_transfer"
    far_transfer = "far_transfer"
    independent_no_ai = "independent_no_ai"


class ConsentStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ContaminationClass(str, Enum):
    CLEAN = "CLEAN"
    AI_ASSISTED = "AI_ASSISTED"
    HINT_ASSISTED = "HINT_ASSISTED"
    ANSWER_EXPOSED = "ANSWER_EXPOSED"
    INVALIDATED = "INVALIDATED"
    UNKNOWN = "UNKNOWN"


class MeasurementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AVAILABLE = "AVAILABLE"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    INVALIDATED = "INVALIDATED"


class PilotStageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: PilotStage
    eligibility: dict[str, Any] = Field(default_factory=dict)
    window_days: int | None = Field(default=None, ge=0)
    window_before_days: int = Field(default=1, ge=0)
    window_after_days: int = Field(default=1, ge=0)
    required_evidence: list[str] = Field(default_factory=list)
    ai_assistance_policy: str
    completion_criteria: dict[str, Any] = Field(default_factory=dict)
    contamination_rules: list[str] = Field(default_factory=list)


class PilotEnrollment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    protocol_id: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=40)
    cohort_id: str = Field(min_length=1, max_length=120)
    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    consent_version: str | None = Field(default=None, max_length=40)
    consent_recorded_at: datetime | None = None
    enrolled_at: datetime
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_consent(self) -> "PilotEnrollment":
        for value in (self.enrolled_at, self.consent_recorded_at, self.revoked_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("pilot enrollment timestamps must be timezone-aware")
        if self.consent_status == ConsentStatus.GRANTED:
            if not self.consent_version or self.consent_recorded_at is None:
                raise ValueError("granted consent requires version and recorded_at")
        if self.consent_status == ConsentStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked consent requires revoked_at")
        return self


class PilotAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID = Field(default_factory=uuid4)
    enrollment_id: UUID
    student_id: UUID
    protocol_id: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=40)
    cohort_id: str = Field(min_length=1, max_length=120)
    arm: str = Field(min_length=1, max_length=80)
    assignment_method: str = Field(min_length=1, max_length=120)
    assigned_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "PilotAssignment":
        if self.assigned_at.tzinfo is None or self.assigned_at.utcoffset() is None:
            raise ValueError("assignment timestamp must be timezone-aware")
        return self


class MeasurementSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: UUID
    student_id: UUID
    enrollment_id: UUID
    protocol_id: str
    protocol_version: str
    phase: str
    measurement_due_at: datetime
    window_open_at: datetime
    window_close_at: datetime
    completed_at: datetime | None = None
    status: MeasurementStatus = MeasurementStatus.SCHEDULED
    evidence_event_ids: list[UUID] = Field(default_factory=list)
    invalidation_reason: str | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "MeasurementSchedule":
        values = (
            self.measurement_due_at,
            self.window_open_at,
            self.window_close_at,
            self.completed_at,
        )
        if any(value is not None and (value.tzinfo is None or value.utcoffset() is None) for value in values):
            raise ValueError("measurement timestamps must be timezone-aware")
        if not self.window_open_at <= self.measurement_due_at <= self.window_close_at:
            raise ValueError("measurement window must contain its due time")
        return self


class ContaminationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: ContaminationClass
    reason_codes: list[str] = Field(default_factory=list)
    evaluation_phase: str | None = None
    independent_evidence_allowed: bool = False


def independent_evaluation_guard(
    phase: str, *, assistance_requested: bool = False
) -> dict[str, Any]:
    """Keep help available while invalidating contaminated independent evidence."""

    independent = phase in _EVALUATION_PHASES
    return {
        "phase": phase,
        "answer_generation_allowed": not independent,
        "solution_reveal_allowed": not independent,
        "hint_ladder_allowed": not independent,
        "assistance_requested": assistance_requested,
        "invalidate_independent_evidence": independent and assistance_requested,
    }


class AnalysisManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = "pilot-analysis-manifest/v1"
    protocol_snapshot: dict[str, Any]
    model_versions: list[str] = Field(default_factory=list)
    policy_version: str = "policy/v2"
    event_cutoff: datetime | None = None
    exclusion_rules: list[str] = Field(default_factory=list)
    endpoint_definitions: dict[str, Any] = Field(default_factory=dict)
    code_sha: str
    analysis_version: str
    input_checksum: str


class PilotAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str = "pilot-analysis-report/v1"
    artifact_id: str | None = None
    mode: str
    evidence_level: str
    protocol: dict[str, Any]
    cohort: dict[str, Any]
    data_cutoff: datetime | None
    n_students: int
    n_events: int
    missingness: dict[str, int]
    contamination: dict[str, int]
    stage_statuses: dict[str, dict[str, Any]] = Field(default_factory=dict)
    endpoint_results: dict[str, Any]
    data_quality: dict[str, Any]
    limitations: list[str]
    claim_guard: dict[str, Any]
    manifest: AnalysisManifest
    status: str


class PilotDataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    checks: dict[str, Any]
    blockers: list[str] = Field(default_factory=list)
    endpoint_allowed: bool
    n_events: int
    missingness: dict[str, int] = Field(default_factory=dict)


class EvidenceRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=128)
    claim: str = Field(min_length=1)
    evidence_level: str
    protocol_id: str | None = None
    cohort_id: str | None = None
    data_cutoff: datetime | None = None
    analysis_version: str
    source: str
    status: str = "PENDING"
    analysis_artifact_id: str | None = None
    created_at: datetime


_EVALUATION_PHASES = frozenset(
    {
        "delayed_test",
        "delayed_7d",
        "delayed_30d",
        "near_transfer",
        "far_transfer",
        "independent_no_ai",
    }
)
_TRANSFER_PHASES = frozenset({"near_transfer", "far_transfer"})
_EVIDENCE_LEVELS = frozenset(
    {"contract", "offline", "observational", "randomized", "commercial"}
)
_REGISTRY_STATUSES = frozenset(
    {"PENDING", "SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE", "RETRACTED"}
)


def _default_stage_specs() -> dict[str, dict[str, Any]]:
    return {
        "baseline": {
            "window_days": 0,
            "required_evidence": ["correctness", "knowledge_ref"],
            "ai_assistance_policy": "allowed_but_not_independent",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["record_assistance", "exclude_answer_exposed"],
        },
        "practice": {
            "window_days": 0,
            "required_evidence": ["learning_event"],
            "ai_assistance_policy": "allowed",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["classify_assistance"],
        },
        "immediate_test": {
            "window_days": 0,
            "required_evidence": ["correctness", "evaluation_phase"],
            "ai_assistance_policy": "allowed_but_excluded_if_present",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["exclude_assisted_evidence"],
        },
        "delayed_7d": {
            "window_days": 7,
            "required_evidence": ["correctness", "evaluation_phase", "protocol_version"],
            "ai_assistance_policy": "forbidden_for_endpoint",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["ai_assisted_is_not_independent", "window_only"],
        },
        "delayed_30d": {
            "window_days": 30,
            "required_evidence": ["correctness", "evaluation_phase", "protocol_version"],
            "ai_assistance_policy": "forbidden_for_endpoint",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["ai_assisted_is_not_independent", "window_only"],
        },
        "near_transfer": {
            "window_days": 0,
            "required_evidence": ["correctness", "knowledge_ref", "evaluation_phase"],
            "ai_assistance_policy": "forbidden_for_endpoint",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["explicit_transfer_only", "exclude_assisted_evidence"],
        },
        "far_transfer": {
            "window_days": 0,
            "required_evidence": ["correctness", "knowledge_ref", "evaluation_phase"],
            "ai_assistance_policy": "forbidden_for_endpoint",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["explicit_transfer_only", "exclude_assisted_evidence"],
        },
        "independent_no_ai": {
            "window_days": 0,
            "required_evidence": ["correctness", "independent_mode", "ai_assisted"],
            "ai_assistance_policy": "forbidden",
            "completion_criteria": {"minimum_events": 1},
            "contamination_rules": ["assistance_invalidates", "answer_exposure_invalidates"],
        },
    }


def _window_days(value: Any, default: int | None) -> int | None:
    if isinstance(value, Mapping):
        for key in ("window_days", "horizon_days", "offset_days", "days"):
            if value.get(key) is not None:
                return int(value[key])
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        if digits:
            return int(digits)
    return default


def protocol_stage_specs(protocol: Any) -> dict[str, dict[str, Any]]:
    """Merge protocol-configured windows over the single default stage contract."""

    defaults = _default_stage_specs()
    configured = getattr(protocol, "evaluation_windows", {}) or {}
    result: dict[str, dict[str, Any]] = {}
    for name, base in defaults.items():
        row = dict(base)
        if name in configured:
            value = configured[name]
            row["window_days"] = _window_days(value, row["window_days"])
            if isinstance(value, Mapping):
                for key in ("window_before_days", "window_after_days"):
                    if value.get(key) is not None:
                        row[key] = int(value[key])
        # Preserve legacy delayed/baseline configuration without changing the
        # explicit modern phase names.
        if name == "delayed_7d" and "delayed" in configured:
            row["window_days"] = _window_days(configured["delayed"], 7)
        if name == "baseline" and "baseline" in configured:
            row["window_days"] = _window_days(configured["baseline"], 0)
        row["stage"] = name
        result[name] = row
    return result


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _phase(obj: Any, explicit: str | None = None) -> str | None:
    raw = explicit if explicit is not None else _value(obj, "evaluation_phase")
    return getattr(raw, "value", raw) if raw is not None else None


def _intervention(obj: Any, intervention: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = intervention if intervention is not None else _value(obj, "intervention")
    return dict(raw) if isinstance(raw, Mapping) else {}


class EvidenceContaminationClassifier:
    """The single contamination classifier used by all pilot endpoints."""

    @classmethod
    def classify(
        cls,
        event: Any,
        *,
        intervention: Mapping[str, Any] | None = None,
        evaluation_phase: str | None = None,
    ) -> ContaminationResult:
        phase = _phase(event, evaluation_phase)
        meta = _intervention(event, intervention)
        reason_codes: list[str] = []

        assistance_requested = bool(
            _value(event, "assistance_requested", False)
            or meta.get("assistance_requested", False)
        )
        invalidated = bool(
            _value(event, "invalidated", False)
            or meta.get("invalidated", False)
            or meta.get("invalidate_independent_evidence", False)
        )
        answer_exposed = bool(
            _value(event, "answer_exposed", False)
            or _value(event, "solution_revealed", False)
            or _value(event, "answer_seen", False)
            or meta.get("answer_exposed", False)
            or meta.get("solution_revealed", False)
            or meta.get("answer_seen", False)
        )
        hints_used = _value(event, "hints_used", None)
        if hints_used is None:
            hints_used = meta.get("hints_used", meta.get("hints", 0))
        hint_assisted = bool(hints_used and int(hints_used) > 0) or bool(
            meta.get("hint_assisted", False) or meta.get("hint_heavy", False)
        )
        ai_assisted = _value(event, "ai_assisted", None)
        if ai_assisted is None:
            ai_assisted = meta.get("ai_assisted")
        independent_mode = _value(event, "independent_mode", None)
        if independent_mode is None:
            independent_mode = meta.get("independent_mode")

        if assistance_requested or invalidated:
            if assistance_requested:
                reason_codes.append("assistance_requested_invalidates_attempt")
            if invalidated:
                reason_codes.append("explicit_invalidation")
            classification = ContaminationClass.INVALIDATED
        elif answer_exposed:
            reason_codes.append("answer_or_solution_exposed")
            classification = ContaminationClass.ANSWER_EXPOSED
        elif ai_assisted is True:
            reason_codes.append("ai_assistance_flag_true")
            classification = ContaminationClass.AI_ASSISTED
        elif hint_assisted:
            reason_codes.append("hint_assistance_present")
            classification = ContaminationClass.HINT_ASSISTED
        elif phase in _EVALUATION_PHASES and (
            ai_assisted is not False or independent_mode is not True
        ):
            reason_codes.append("independence_flags_missing_or_false")
            classification = ContaminationClass.UNKNOWN
        else:
            reason_codes.append("explicit_no_contamination_signal")
            classification = ContaminationClass.CLEAN

        return ContaminationResult(
            classification=classification,
            reason_codes=reason_codes,
            evaluation_phase=phase,
            independent_evidence_allowed=(classification == ContaminationClass.CLEAN),
        )


def classify_evidence(event: Any, *, evaluation_phase: str | None = None) -> ContaminationResult:
    return EvidenceContaminationClassifier.classify(event, evaluation_phase=evaluation_phase)


def schedule_measurement(
    enrollment: PilotEnrollment,
    protocol: Any,
    phase: str,
    *,
    anchor_at: datetime,
    existing: MeasurementSchedule | None = None,
) -> MeasurementSchedule:
    """Create a deterministic schedule; repeated calls return the same identity."""

    if anchor_at.tzinfo is None or anchor_at.utcoffset() is None:
        raise ValueError("anchor_at must be timezone-aware")
    if existing is not None:
        if (
            existing.student_id == enrollment.student_id
            and existing.protocol_id == enrollment.protocol_id
            and existing.protocol_version == enrollment.protocol_version
            and existing.phase == phase
        ):
            return existing
        raise ValueError("existing measurement schedule does not match enrollment")
    specs = protocol_stage_specs(protocol)
    if phase not in specs:
        raise ValueError(f"unsupported pilot phase: {phase}")
    spec = specs[phase]
    offset = int(spec.get("window_days") or 0)
    due = anchor_at + timedelta(days=offset)
    before = int(spec.get("window_before_days", 1))
    after = int(spec.get("window_after_days", 1))
    schedule_id = uuid5(
        NAMESPACE_URL,
        f"mneme/pilot/{enrollment.student_id}/{enrollment.protocol_id}/{enrollment.protocol_version}/{phase}",
    )
    return MeasurementSchedule(
        schedule_id=schedule_id,
        student_id=enrollment.student_id,
        enrollment_id=enrollment.enrollment_id,
        protocol_id=enrollment.protocol_id,
        protocol_version=enrollment.protocol_version,
        phase=phase,
        measurement_due_at=due,
        window_open_at=due - timedelta(days=before),
        window_close_at=due + timedelta(days=after),
    )


def refresh_measurement_status(
    schedule: MeasurementSchedule, *, now: datetime
) -> MeasurementSchedule:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if schedule.status in {MeasurementStatus.COMPLETED, MeasurementStatus.INVALIDATED}:
        return schedule
    if now < schedule.window_open_at:
        status = MeasurementStatus.SCHEDULED
    elif now <= schedule.window_close_at:
        status = MeasurementStatus.AVAILABLE
    else:
        status = MeasurementStatus.MISSED
    return schedule.model_copy(update={"status": status})


def complete_measurement(
    schedule: MeasurementSchedule,
    *,
    completed_at: datetime,
    evidence_event_ids: Sequence[UUID] = (),
    contamination: ContaminationClass = ContaminationClass.CLEAN,
) -> MeasurementSchedule:
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("completed_at must be timezone-aware")
    in_window = schedule.window_open_at <= completed_at <= schedule.window_close_at
    if contamination != ContaminationClass.CLEAN:
        return schedule.model_copy(
            update={
                "status": MeasurementStatus.INVALIDATED,
                "completed_at": completed_at,
                "evidence_event_ids": list(evidence_event_ids),
                "invalidation_reason": f"contamination:{contamination.value}",
            }
        )
    if not in_window:
        return schedule.model_copy(
            update={
                "status": MeasurementStatus.INVALIDATED,
                "completed_at": completed_at,
                "evidence_event_ids": list(evidence_event_ids),
                "invalidation_reason": "measurement_outside_window",
            }
        )
    return schedule.model_copy(
        update={
            "status": MeasurementStatus.COMPLETED,
            "completed_at": completed_at,
            "evidence_event_ids": list(evidence_event_ids),
        }
    )


def pilot_stage_status(
    protocol: Any,
    observations: Iterable[Any],
    phase: str,
    *,
    data_cutoff: datetime | None = None,
) -> dict[str, Any]:
    """Return a non-fabricating stage status for operations/reporting."""

    specs = protocol_stage_specs(protocol)
    if phase not in specs:
        raise ValueError(f"unsupported pilot phase: {phase}")
    rows = _eval_rows(observations)
    if not rows:
        return {"phase": phase, "status": "PENDING", "n_events": 0}
    cutoff = data_cutoff
    if cutoff is None:
        dates = [_as_datetime(_value(row, "occurred_at")) for row in rows]
        valid = [date for date in dates if date is not None]
        cutoff = max(valid) if valid else None
    if phase in {"delayed_7d", "delayed_30d"}:
        anchors = [
            _as_datetime(_value(row, "occurred_at"))
            for row in rows
            if _phase(row) in {"baseline", "practice"}
        ]
        anchor_dates = [anchor for anchor in anchors if anchor is not None]
        days = int(specs[phase].get("window_days") or 0)
        if anchor_dates and cutoff is not None and cutoff < min(anchor_dates) + timedelta(days=days):
            return {"phase": phase, "status": "WINDOW_NOT_REACHED", "n_events": 0}
    selected = [row for row in rows if _phase(row) == phase]
    if not selected:
        return {"phase": phase, "status": "INSUFFICIENT_EVIDENCE", "n_events": 0}
    clean = [
        row
        for row in selected
        if EvidenceContaminationClassifier.classify(row).classification == ContaminationClass.CLEAN
    ]
    if not clean:
        return {
            "phase": phase,
            "status": "INSUFFICIENT_EVIDENCE",
            "n_events": len(selected),
            "contamination_count": len(selected),
        }
    return {"phase": phase, "status": "COMPLETED", "n_events": len(clean)}


def enroll_pilot_student(
    *,
    student_id: UUID,
    protocol: Any,
    cohort_id: str,
    consent_status: ConsentStatus,
    enrolled_at: datetime,
    consent_version: str | None = None,
    consent_recorded_at: datetime | None = None,
) -> PilotEnrollment:
    """Technical consent gate; legal policy remains an owner decision."""

    requires_consent = bool(getattr(protocol, "requires_consent", True))
    if requires_consent and consent_status != ConsentStatus.GRANTED:
        raise PermissionError("pilot enrollment requires GRANTED consent")
    return PilotEnrollment(
        student_id=student_id,
        protocol_id=str(protocol.protocol_id),
        protocol_version=str(protocol.version),
        cohort_id=cohort_id,
        consent_status=consent_status,
        consent_version=consent_version,
        consent_recorded_at=consent_recorded_at,
        enrolled_at=enrolled_at,
    )


def revoke_pilot_consent(
    enrollment: PilotEnrollment, *, revoked_at: datetime
) -> PilotEnrollment:
    if revoked_at.tzinfo is None or revoked_at.utcoffset() is None:
        raise ValueError("revoked_at must be timezone-aware")
    return enrollment.model_copy(
        update={"consent_status": ConsentStatus.REVOKED, "revoked_at": revoked_at}
    )


def assign_pilot_student(enrollment: PilotEnrollment, protocol: Any) -> PilotAssignment:
    """Deterministic assignment from the registered protocol's two arms."""

    treatment = str((getattr(protocol, "treatment_definition", {}) or {}).get("arm", "treatment"))
    control = str((getattr(protocol, "control_definition", {}) or {}).get("arm", "control"))
    digest = hashlib.sha256(
        f"{protocol.protocol_id}:{protocol.version}:{enrollment.student_id}".encode()
    ).digest()
    arm = treatment if int.from_bytes(digest[:8], "big") % 2 == 0 else control
    return PilotAssignment(
        enrollment_id=enrollment.enrollment_id,
        student_id=enrollment.student_id,
        protocol_id=enrollment.protocol_id,
        protocol_version=enrollment.protocol_version,
        cohort_id=enrollment.cohort_id,
        arm=arm,
        assignment_method=str(protocol.assignment_method),
        assigned_at=enrollment.enrolled_at,
    )


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _eval_rows(observations: Iterable[Any]) -> list[Any]:
    rows: list[Any] = []
    for row in observations:
        if hasattr(row, "to_evaluation"):
            rows.append(row.to_evaluation())
        else:
            rows.append(row)
    return rows


def _row_key(row: Any, index: int) -> str:
    event_id = _value(row, "event_id")
    return str(event_id) if event_id is not None else f"row-{index}"


def _row_serializable(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json", exclude_none=False)
    if hasattr(row, "__dict__"):
        return {key: value for key, value in vars(row).items() if not key.startswith("_")}
    if isinstance(row, Mapping):
        return dict(row)
    return {"value": str(row)}


def check_pilot_data_quality(
    observations: Iterable[Any],
    *,
    protocol: Any | None = None,
    assignments: Iterable[Any] | None = None,
    enrollments: Iterable[Any] | None = None,
    schedules: Iterable[Any] | None = None,
    data_cutoff: datetime | None = None,
) -> PilotDataQualityReport:
    rows = list(observations)
    checks: dict[str, Any] = {}
    blockers: list[str] = []
    missingness: Counter[str] = Counter()

    keys = [str(_value(row, "event_id")) for row in rows if _value(row, "event_id") is not None]
    duplicate_count = len(keys) - len(set(keys))
    checks["duplicate_events"] = max(0, duplicate_count)
    if duplicate_count > 0:
        blockers.append("duplicate_events")

    seen_students: set[str] = set()
    has_delayed = False
    has_baseline = False
    for index, row in enumerate(rows):
        student_id = _value(row, "student_id")
        if student_id is not None:
            seen_students.add(str(student_id))
        knowledge_ref = _value(row, "knowledge_ref")
        if knowledge_ref is None:
            refs = _value(row, "knowledge_refs")
            if not refs:
                missingness["knowledge_ref"] += 1
        occurred_at = _as_datetime(_value(row, "occurred_at"))
        received_at = _as_datetime(_value(row, "received_at"))
        if occurred_at is None:
            missingness["timestamps"] += 1
        elif occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            missingness["naive_timestamps"] += 1
            blockers.append("naive_timestamps")
        if received_at is not None and occurred_at is not None and received_at < occurred_at:
            missingness["clock_anomalies"] += 1
        for duration_name in (
            "time_spent_seconds",
            "active_learning_seconds",
            "active_minutes",
        ):
            duration = _value(row, duration_name)
            if duration is not None and (float(duration) < 0 or float(duration) > 86400):
                missingness["impossible_durations"] += 1
                blockers.append("impossible_durations")
        phase = _phase(row)
        if phase is None:
            missingness["evaluation_phase"] += 1
        if phase in _EVALUATION_PHASES:
            has_delayed = has_delayed or phase.startswith("delayed")
        if phase in {"baseline", "practice"}:
            has_baseline = True
        if _value(row, "protocol_version") is None:
            missingness["protocol_version"] += 1
        if data_cutoff is not None and occurred_at is not None and occurred_at > data_cutoff:
            missingness["after_data_cutoff"] += 1
        if index > 0:
            previous = _as_datetime(_value(rows[index - 1], "occurred_at"))
            if previous is not None and occurred_at is not None and occurred_at < previous:
                missingness["event_ordering_anomalies"] += 1

    checks.update({key: int(value) for key, value in missingness.items()})
    if has_delayed and not has_baseline:
        blockers.append("missing_baseline")

    assignment_rows = list(assignments or [])
    enrollment_rows = list(enrollments or [])
    enrolled_ids = {str(_value(row, "student_id")) for row in enrollment_rows}
    orphan_assignments = sum(
        1 for row in assignment_rows if enrolled_ids and str(_value(row, "student_id")) not in enrolled_ids
    )
    checks["orphan_assignments"] = orphan_assignments
    if orphan_assignments:
        blockers.append("orphan_assignments")

    contamination_count = 0
    for row in rows:
        result = EvidenceContaminationClassifier.classify(row)
        if _phase(row) in _EVALUATION_PHASES and result.classification != ContaminationClass.CLEAN:
            contamination_count += 1
    checks["contaminated_independent_attempts"] = contamination_count
    if contamination_count:
        missingness["contaminated_independent_attempts"] = contamination_count

    schedule_rows = list(schedules or [])
    window_violations = sum(
        1
        for row in schedule_rows
        if _value(row, "completed_at") is not None
        and _value(row, "status") in {MeasurementStatus.INVALIDATED, "INVALIDATED"}
        and _value(row, "invalidation_reason") == "measurement_outside_window"
    )
    checks["measurement_window_violations"] = window_violations
    if window_violations:
        blockers.append("measurement_window_violations")

    checks["missing_knowledge_ref"] = int(missingness.get("knowledge_ref", 0))
    checks["missing_timestamps"] = int(missingness.get("timestamps", 0))
    checks["missing_evaluation_phase"] = int(missingness.get("evaluation_phase", 0))
    checks["missing_protocol_version"] = int(missingness.get("protocol_version", 0))
    checks["event_ordering_anomalies"] = int(missingness.get("event_ordering_anomalies", 0))

    # Missing labels are warnings for mixed historical data; hard structural
    # anomalies block endpoint calculation.
    hard_missing = sum(
        int(missingness.get(key, 0))
        for key in ("timestamps", "naive_timestamps", "impossible_durations")
    )
    if hard_missing:
        blockers.extend(key for key in ("timestamps",) if missingness.get(key))
    unique_blockers = sorted(set(blockers))
    status = "FAIL" if unique_blockers else ("WARN" if missingness else "PASS")
    return PilotDataQualityReport(
        status=status,
        checks=checks,
        blockers=unique_blockers,
        endpoint_allowed=not unique_blockers,
        n_events=len(rows),
        missingness=dict(missingness),
    )


def _clean_rows(rows: Iterable[Any], *, phase: str | None = None) -> tuple[list[Any], Counter[str]]:
    selected: list[Any] = []
    counts: Counter[str] = Counter()
    for row in rows:
        if phase is not None and _phase(row) != phase:
            continue
        result = EvidenceContaminationClassifier.classify(row)
        counts[result.classification.value] += 1
        if result.classification == ContaminationClass.CLEAN:
            selected.append(row)
    return selected, counts


def _endpoint_result(
    *,
    value: float | None,
    n_students: int,
    n_events: int,
    missingness: Mapping[str, int] | None = None,
    exclusion_count: int = 0,
    contamination_count: int = 0,
    protocol_version: str | None = None,
    data_cutoff: datetime | None = None,
    evidence_level: str = "observational",
    status: str = "OK",
    confidence_interval: dict[str, float] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "value": value,
        "confidence_interval": confidence_interval,
        "n_students": n_students,
        "n_events": n_events,
        "missingness": dict(missingness or {}),
        "exclusion_count": exclusion_count,
        "contamination_count": contamination_count,
        "protocol_version": protocol_version,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "evidence_level": evidence_level,
        "status": status,
        **extra,
    }


def _binary_interval(successes: int, total: int) -> dict[str, float] | None:
    if total < 2:
        return None
    from services.evaluation_os import _interval

    result = _interval(successes, total)
    lower = result["lower_95"]
    upper = result["upper_95"]
    if lower is None or upper is None:
        return None
    return {
        "lower_95": float(lower),
        "upper_95": float(upper),
    }


def compute_retention_endpoint(
    observations: Iterable[Any],
    *,
    horizon_days: int,
    protocol_version: str | None = None,
    data_cutoff: datetime | None = None,
) -> dict[str, Any]:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    rows = _eval_rows(observations)
    clean, contamination = _clean_rows(rows)
    anchors: dict[str, datetime] = {}
    for row in clean:
        student = _value(row, "student_id")
        occurred = _as_datetime(_value(row, "occurred_at"))
        if student is not None and occurred is not None:
            key = str(student)
            anchors[key] = min(anchors.get(key, occurred), occurred)
    cutoff = data_cutoff
    if cutoff is None and rows:
        timestamps = [_as_datetime(_value(row, "occurred_at")) for row in rows]
        valid = [stamp for stamp in timestamps if stamp is not None]
        cutoff = max(valid) if valid else None
    mature: list[bool] = []
    missing_window = 0
    clean_by_student: defaultdict[str, list[datetime]] = defaultdict(list)
    for row in clean:
        student = _value(row, "student_id")
        occurred = _as_datetime(_value(row, "occurred_at"))
        if student is not None and occurred is not None:
            clean_by_student[str(student)].append(occurred)
    for student, anchor in anchors.items():
        open_at = anchor + timedelta(days=horizon_days - 1)
        close_at = anchor + timedelta(days=horizon_days + 1)
        if cutoff is None or cutoff < close_at:
            missing_window += 1
            continue
        mature.append(
            any(open_at <= stamp < close_at for stamp in clean_by_student.get(student, []))
        )
    if not mature:
        status = "WINDOW_NOT_REACHED" if missing_window else "INSUFFICIENT_EVIDENCE"
        return _endpoint_result(
            value=None,
            n_students=0,
            n_events=len(rows),
            missingness={"window_not_reached": missing_window} if missing_window else {"no_anchor": 1},
            contamination_count=sum(contamination.values()) - contamination[ContaminationClass.CLEAN.value],
            protocol_version=protocol_version,
            data_cutoff=cutoff,
            status=status,
        )
    successes = sum(mature)
    return _endpoint_result(
        value=round(successes / len(mature), 6),
        n_students=len(mature),
        n_events=len(rows),
        contamination_count=sum(contamination.values()) - contamination[ContaminationClass.CLEAN.value],
        protocol_version=protocol_version,
        data_cutoff=cutoff,
        confidence_interval=_binary_interval(successes, len(mature)),
    )


def _phase_accuracy_endpoint(
    observations: Iterable[Any],
    *,
    phase: str,
    protocol_version: str | None = None,
    data_cutoff: datetime | None = None,
) -> dict[str, Any]:
    rows = _eval_rows(observations)
    phase_rows = [row for row in rows if _phase(row) == phase]
    clean, contamination = _clean_rows(phase_rows, phase=phase)
    if not clean:
        return _endpoint_result(
            value=None,
            n_students=0,
            n_events=len(phase_rows),
            missingness={"no_clean_evidence": len(phase_rows) == 0},
            exclusion_count=len(phase_rows),
            contamination_count=len(phase_rows),
            protocol_version=protocol_version,
            data_cutoff=data_cutoff,
            status="INSUFFICIENT_EVIDENCE",
        )
    successes = sum(bool(_value(row, "is_correct", False)) for row in clean)
    return _endpoint_result(
        value=round(successes / len(clean), 6),
        n_students=len({str(_value(row, "student_id")) for row in clean}),
        n_events=len(clean),
        exclusion_count=len(phase_rows) - len(clean),
        contamination_count=sum(contamination.values()) - contamination[ContaminationClass.CLEAN.value],
        protocol_version=protocol_version,
        data_cutoff=data_cutoff,
        confidence_interval=_binary_interval(successes, len(clean)),
    )


def compute_near_transfer(observations: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
    return _phase_accuracy_endpoint(observations, phase="near_transfer", **kwargs)


def compute_transfer_endpoint(
    observations: Iterable[Any], *, phase: str, **kwargs: Any
) -> dict[str, Any]:
    if phase not in _TRANSFER_PHASES:
        raise ValueError("transfer phase must be near_transfer or far_transfer")
    return _phase_accuracy_endpoint(observations, phase=phase, **kwargs)


def compute_independent_accuracy(observations: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
    return _phase_accuracy_endpoint(observations, phase="independent_no_ai", **kwargs)


def compute_jol_calibration(
    observations: Iterable[Any],
    *,
    protocol_version: str | None = None,
    data_cutoff: datetime | None = None,
) -> dict[str, Any]:
    rows = _eval_rows(observations)
    valid: list[tuple[float, float, Any]] = []
    contaminated = 0
    missing = Counter[str]()
    for row in rows:
        confidence = _value(row, "jol_confidence")
        if confidence is None:
            continue
        jol_at = _as_datetime(_value(row, "jol_at"))
        outcome_at = _as_datetime(_value(row, "outcome_revealed_at"))
        if jol_at is None or outcome_at is None:
            missing["jol_or_outcome_timestamp"] += 1
            continue
        if jol_at >= outcome_at:
            contaminated += 1
            continue
        result = EvidenceContaminationClassifier.classify(row)
        if result.classification != ContaminationClass.CLEAN:
            contaminated += 1
            continue
        valid.append((float(confidence), float(bool(_value(row, "is_correct", False))), row))
    if not valid:
        return _endpoint_result(
            value=None,
            n_students=0,
            n_events=len(rows),
            missingness=dict(missing),
            exclusion_count=contaminated,
            contamination_count=contaminated,
            protocol_version=protocol_version,
            data_cutoff=data_cutoff,
            status="CONTAMINATED_JOL" if contaminated else "INSUFFICIENT_EVIDENCE",
            calibration_error=None,
            overconfidence_rate=None,
            underconfidence_rate=None,
            brier_like_score=None,
        )
    errors = [abs(confidence - outcome) for confidence, outcome, _ in valid]
    over = [confidence > outcome for confidence, outcome, _ in valid]
    under = [confidence < outcome for confidence, outcome, _ in valid]
    brier = [((confidence - outcome) ** 2) for confidence, outcome, _ in valid]
    return _endpoint_result(
        value=round(sum(errors) / len(errors), 6),
        n_students=len({str(_value(row, "student_id")) for _, _, row in valid}),
        n_events=len(valid),
        exclusion_count=contaminated,
        contamination_count=contaminated,
        protocol_version=protocol_version,
        data_cutoff=data_cutoff,
        calibration_error=round(sum(errors) / len(errors), 6),
        overconfidence_rate=round(sum(over) / len(over), 6),
        underconfidence_rate=round(sum(under) / len(under), 6),
        brier_like_score=round(sum(brier) / len(brier), 6),
    )


def compute_rmg_am(
    observations: Iterable[Any],
    *,
    protocol_version: str | None = None,
    data_cutoff: datetime | None = None,
    minimum_evidence: int = 1,
) -> dict[str, Any]:
    """Compute retained mastery gain / measured active learning minutes.

    ``time_spent_seconds`` is intentionally ignored.  A row must provide an
    explicit active-learning measure; excluded idle/background/upload/AI/system
    time is subtracted before aggregation.
    """

    rows = _eval_rows(observations)
    valid: list[tuple[float, float, Any]] = []
    missing = Counter[str]()
    contamination_count = 0
    for row in rows:
        result = EvidenceContaminationClassifier.classify(row)
        if result.classification != ContaminationClass.CLEAN:
            contamination_count += 1
            continue
        active = _value(row, "active_learning_seconds")
        if active is None:
            explicit_minutes = _value(row, "active_minutes")
            active = float(explicit_minutes) * 60.0 if explicit_minutes is not None else None
        if active is None:
            missing["active_learning_seconds"] += 1
            continue
        gain = _value(row, "retained_mastery_gain")
        if gain is None:
            gain = _value(row, "mastery_gain")
        if gain is None:
            before = _value(row, "baseline_mastery")
            retained = _value(row, "retained_mastery")
            gain = float(retained) - float(before) if before is not None and retained is not None else None
        if gain is None:
            missing["retained_mastery_gain"] += 1
            continue
        excluded = sum(
            float(_value(row, name, 0.0) or 0.0)
            for name in (
                "idle_seconds",
                "background_seconds",
                "upload_processing_seconds",
                "ai_latency_seconds",
                "system_wait_seconds",
            )
        )
        net_active = float(active) - excluded
        if net_active <= 0:
            missing["non_positive_active_time"] += 1
            continue
        valid.append((float(gain), net_active / 60.0, row))
    if len(valid) < minimum_evidence:
        return _endpoint_result(
            value=None,
            n_students=len({str(_value(row, "student_id")) for _, _, row in valid}),
            n_events=len(rows),
            missingness=dict(missing),
            exclusion_count=len(rows) - len(valid),
            contamination_count=contamination_count,
            protocol_version=protocol_version,
            data_cutoff=data_cutoff,
            status="INSUFFICIENT_ACTIVITY_EVIDENCE",
        )
    total_gain = sum(gain for gain, _, _ in valid)
    total_minutes = sum(minutes for _, minutes, _ in valid)
    return _endpoint_result(
        value=round(total_gain / total_minutes, 6) if total_minutes > 0 else None,
        n_students=len({str(_value(row, "student_id")) for _, _, row in valid}),
        n_events=len(valid),
        missingness=dict(missing),
        exclusion_count=len(rows) - len(valid),
        contamination_count=contamination_count,
        protocol_version=protocol_version,
        data_cutoff=data_cutoff,
        active_learning_minutes=round(total_minutes, 6),
    )


def compute_pilot_endpoints(
    protocol: Any,
    observations: Iterable[Any],
    *,
    data_cutoff: datetime | None = None,
    quality: PilotDataQualityReport | None = None,
) -> dict[str, dict[str, Any]]:
    rows = _eval_rows(observations)
    version = str(protocol.version)
    if quality is not None and not quality.endpoint_allowed:
        return {
            name: _endpoint_result(
                value=None,
                n_students=0,
                n_events=len(rows),
                missingness={"data_quality": 1},
                protocol_version=version,
                data_cutoff=data_cutoff,
                status="DATA_QUALITY_BLOCKED",
            )
            for name in (
                "retention_7d",
                "retention_30d",
                "near_transfer",
                "far_transfer",
                "independent_no_ai_accuracy",
                "jol_calibration",
                "retained_mastery_gain_per_active_minute",
            )
        }
    return {
        "retention_7d": compute_retention_endpoint(rows, horizon_days=7, protocol_version=version, data_cutoff=data_cutoff),
        "retention_30d": compute_retention_endpoint(rows, horizon_days=30, protocol_version=version, data_cutoff=data_cutoff),
        "near_transfer": compute_near_transfer(rows, protocol_version=version, data_cutoff=data_cutoff),
        "far_transfer": compute_transfer_endpoint(rows, phase="far_transfer", protocol_version=version, data_cutoff=data_cutoff),
        "independent_no_ai_accuracy": compute_independent_accuracy(rows, protocol_version=version, data_cutoff=data_cutoff),
        "jol_calibration": compute_jol_calibration(rows, protocol_version=version, data_cutoff=data_cutoff),
        "retained_mastery_gain_per_active_minute": compute_rmg_am(
            rows,
            protocol_version=version,
            data_cutoff=data_cutoff,
            minimum_evidence=int(getattr(protocol, "minimum_evidence", 1)),
        ),
    }


def _valid_randomized_assignment(
    protocol: Any,
    assignments: Sequence[Any],
    *,
    observed_students: set[str] | None = None,
) -> bool:
    method = str(getattr(protocol, "assignment_method", "")).lower()
    plan = getattr(protocol, "analysis_plan", {}) or {}
    if "random" not in method or plan.get("randomized") is not True:
        return False
    arms = {str(_value(row, "arm")) for row in assignments if _value(row, "arm") is not None}
    treatment = str((getattr(protocol, "treatment_definition", {}) or {}).get("arm", "treatment"))
    control = str((getattr(protocol, "control_definition", {}) or {}).get("arm", "control"))
    students = {str(_value(row, "student_id")) for row in assignments}
    if observed_students and not observed_students.issubset(students):
        return False
    return (
        {treatment, control}.issubset(arms)
        and len(students) == len(assignments)
        and len(students) >= 2
    )


def claim_guard(
    claim: str,
    *,
    mode: str,
    evidence_level: str,
    randomized_valid: bool = False,
) -> dict[str, Any]:
    lower = claim.lower()
    causal_terms = ("improves learning", "causal", "causality", "提高学习", "提升学习效果")
    prohibited = any(term in lower for term in causal_terms)
    allowed = not prohibited or (mode == "RANDOMIZED" and evidence_level == "randomized" and randomized_valid)
    return {
        "claim": claim,
        "allowed": allowed,
        "reason": "registered randomized evidence required for causal learning claims"
        if prohibited and not allowed
        else "claim is within the current evidence boundary",
    }


def _code_sha() -> str:
    return os.environ.get("GITHUB_SHA") or os.environ.get("MNEME_CODE_SHA") or "unknown"


def run_pilot_validation(
    protocol: Any,
    observations: Iterable[Any],
    *,
    data_cutoff: datetime | None = None,
    assignments: Iterable[Any] | None = None,
    enrollments: Iterable[Any] | None = None,
    schedules: Iterable[Any] | None = None,
    code_sha: str | None = None,
    claim: str = "Mneme improves learning",
) -> PilotAnalysisReport:
    from services.real_user_data import production_analytics_allowed

    rows = [row for row in _eval_rows(observations) if production_analytics_allowed(row)]
    assignment_rows = list(assignments or [])
    quality = check_pilot_data_quality(
        rows,
        protocol=protocol,
        assignments=assignment_rows,
        enrollments=enrollments,
        schedules=schedules,
        data_cutoff=data_cutoff,
    )
    if data_cutoff is None and rows:
        dates = [_as_datetime(_value(row, "occurred_at")) for row in rows]
        valid_dates = [value for value in dates if value is not None]
        data_cutoff = max(valid_dates) if valid_dates else None
    randomized = _valid_randomized_assignment(
        protocol,
        assignment_rows,
        observed_students={str(_value(row, "student_id")) for row in rows},
    )
    mode = "RANDOMIZED" if randomized else ("OBSERVATIONAL" if rows else "DESCRIPTIVE")
    evidence_level = "randomized" if randomized else ("observational" if rows else "contract")
    endpoint_results = compute_pilot_endpoints(protocol, rows, data_cutoff=data_cutoff, quality=quality)
    stage_statuses = {
        phase: pilot_stage_status(protocol, rows, phase, data_cutoff=data_cutoff)
        for phase in protocol_stage_specs(protocol)
    }
    serialized = json.dumps(
        [_row_serializable(row) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    input_checksum = hashlib.sha256(serialized.encode()).hexdigest()
    manifest = AnalysisManifest(
        protocol_snapshot=protocol.model_dump(mode="json") if hasattr(protocol, "model_dump") else dict(protocol),
        model_versions=sorted({str(_value(row, "model_version")) for row in rows if _value(row, "model_version")}),
        event_cutoff=data_cutoff,
        exclusion_rules=list(getattr(protocol, "exclusion_rules", []) or []),
        endpoint_definitions=protocol_stage_specs(protocol),
        code_sha=code_sha or _code_sha(),
        analysis_version=str(getattr(protocol, "analysis_version", "pilot-analysis/v1")),
        input_checksum=input_checksum,
    )
    guard = claim_guard(claim, mode=mode, evidence_level=evidence_level, randomized_valid=randomized)
    cohort_definition = getattr(protocol, "cohort_definition", {}) or {}
    cohort_id = cohort_definition.get("cohort_id") if isinstance(cohort_definition, Mapping) else None
    artifact_payload = json.dumps(
        {"manifest": manifest.model_dump(mode="json"), "endpoints": endpoint_results},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    artifact_id = hashlib.sha256(artifact_payload.encode()).hexdigest()
    if not rows:
        status = "INSUFFICIENT_EVIDENCE"
        limitations = ["no real observations supplied; no synthetic fallback"]
    elif not quality.endpoint_allowed:
        status = "DATA_QUALITY_BLOCKED"
        limitations = ["endpoint calculation blocked by pilot data quality failures"]
    else:
        status = "ANALYSIS_READY"
        limitations = ["descriptive/observational output is not a causal learning-effect claim"]
    return PilotAnalysisReport(
        artifact_id=artifact_id,
        mode=mode,
        evidence_level=evidence_level,
        protocol=protocol.model_dump(mode="json") if hasattr(protocol, "model_dump") else dict(protocol),
        cohort={"cohort_id": cohort_id},
        data_cutoff=data_cutoff,
        n_students=len({str(_value(row, "student_id")) for row in rows}),
        n_events=len(rows),
        missingness=quality.missingness,
        contamination=Counter(
            EvidenceContaminationClassifier.classify(row).classification.value for row in rows
        ),
        stage_statuses=stage_statuses,
        endpoint_results=endpoint_results,
        data_quality=quality.model_dump(mode="json"),
        limitations=limitations,
        claim_guard=guard,
        manifest=manifest,
        status=status,
    )


def replay_pilot_analysis(
    protocol: Any,
    observations: Iterable[Any],
    manifest: AnalysisManifest | Mapping[str, Any],
    *,
    assignments: Iterable[Any] | None = None,
) -> PilotAnalysisReport:
    expected = manifest if isinstance(manifest, AnalysisManifest) else AnalysisManifest.model_validate(manifest)
    report = run_pilot_validation(
        protocol,
        observations,
        data_cutoff=expected.event_cutoff,
        assignments=assignments,
        code_sha=expected.code_sha,
    )
    if report.manifest.input_checksum != expected.input_checksum:
        raise ValueError("analysis replay input checksum mismatch")
    return report


def register_evidence_claim(
    *,
    evidence_id: str,
    claim: str,
    evidence_level: str,
    protocol_id: str | None,
    cohort_id: str | None,
    data_cutoff: datetime | None,
    analysis_version: str,
    source: str,
    status: str = "PENDING",
    analysis_artifact_id: str | None = None,
    analysis_artifact: PilotAnalysisReport | None = None,
    created_at: datetime | None = None,
) -> EvidenceRegistryEntry:
    if evidence_level not in _EVIDENCE_LEVELS:
        raise ValueError(f"unsupported evidence level: {evidence_level}")
    if status not in _REGISTRY_STATUSES:
        raise ValueError(f"unsupported evidence status: {status}")
    if status == "SUPPORTED":
        if analysis_artifact is None or not analysis_artifact_id:
            raise ValueError("SUPPORTED evidence requires an analysis artifact")
        if analysis_artifact.artifact_id != analysis_artifact_id:
            raise ValueError("analysis artifact id does not match evidence registry")
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return EvidenceRegistryEntry(
        evidence_id=evidence_id,
        claim=claim,
        evidence_level=evidence_level,
        protocol_id=protocol_id,
        cohort_id=cohort_id,
        data_cutoff=data_cutoff,
        analysis_version=analysis_version,
        source=source,
        status=status,
        analysis_artifact_id=analysis_artifact_id,
        created_at=timestamp,
    )


async def persist_pilot_enrollment(db: Any, enrollment: PilotEnrollment) -> Any:
    """Idempotently persist enrollment metadata; callers own the transaction."""

    from sqlalchemy import select

    from services.models import PilotEnrollment as Row

    existing = (
        await db.execute(
            select(Row).where(
                Row.student_id == enrollment.student_id,
                Row.protocol_id == enrollment.protocol_id,
                Row.protocol_version == enrollment.protocol_version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Row(
        enrollment_id=enrollment.enrollment_id,
        student_id=enrollment.student_id,
        protocol_id=enrollment.protocol_id,
        protocol_version=enrollment.protocol_version,
        cohort_id=enrollment.cohort_id,
        consent_status=enrollment.consent_status.value,
        consent_version=enrollment.consent_version,
        consent_recorded_at=enrollment.consent_recorded_at,
        enrolled_at=enrollment.enrolled_at,
        revoked_at=enrollment.revoked_at,
    )
    db.add(row)
    await db.flush()
    return row


async def persist_pilot_assignment(db: Any, assignment: PilotAssignment) -> Any:
    from sqlalchemy import select

    from services.models import PilotAssignment as Row

    existing = (
        await db.execute(
            select(Row).where(Row.enrollment_id == assignment.enrollment_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Row(
        assignment_id=assignment.assignment_id,
        enrollment_id=assignment.enrollment_id,
        student_id=assignment.student_id,
        protocol_id=assignment.protocol_id,
        protocol_version=assignment.protocol_version,
        cohort_id=assignment.cohort_id,
        arm=assignment.arm,
        assignment_method=assignment.assignment_method,
        assigned_at=assignment.assigned_at,
    )
    db.add(row)
    await db.flush()
    return row


async def persist_measurement_schedule(db: Any, schedule: MeasurementSchedule) -> Any:
    from sqlalchemy import select

    from services.models import PilotMeasurementSchedule as Row

    existing = (
        await db.execute(select(Row).where(Row.schedule_id == schedule.schedule_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Row(
        schedule_id=schedule.schedule_id,
        student_id=schedule.student_id,
        enrollment_id=schedule.enrollment_id,
        protocol_id=schedule.protocol_id,
        protocol_version=schedule.protocol_version,
        phase=schedule.phase,
        measurement_due_at=schedule.measurement_due_at,
        window_open_at=schedule.window_open_at,
        window_close_at=schedule.window_close_at,
        completed_at=schedule.completed_at,
        status=schedule.status.value,
        evidence_event_ids=[str(value) for value in schedule.evidence_event_ids],
    )
    db.add(row)
    await db.flush()
    return row


async def persist_analysis_artifact(db: Any, report: PilotAnalysisReport) -> Any:
    if not report.artifact_id:
        raise ValueError("analysis report must have an artifact_id")
    from sqlalchemy import select

    from services.models import PilotAnalysisArtifact

    existing = (
        await db.execute(
            select(PilotAnalysisArtifact).where(
                PilotAnalysisArtifact.artifact_id == report.artifact_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = PilotAnalysisArtifact(
        artifact_id=report.artifact_id,
        protocol_id=str(report.protocol["protocol_id"]),
        protocol_version=str(report.protocol["version"]),
        cohort_id=str(report.cohort.get("cohort_id") or "unknown"),
        code_sha=report.manifest.code_sha,
        analysis_version=report.manifest.analysis_version,
        manifest=report.manifest.model_dump(mode="json"),
        report=report.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return row


async def persist_evidence_registry_entry(db: Any, entry: EvidenceRegistryEntry) -> Any:
    if entry.status == "SUPPORTED" and not entry.analysis_artifact_id:
        raise ValueError("SUPPORTED evidence requires an analysis artifact")
    from sqlalchemy import select

    from services.models import PilotAnalysisArtifact
    from services.models import PilotEvidenceRegistry

    if entry.status == "SUPPORTED":
        artifact = (
            await db.execute(
                select(PilotAnalysisArtifact).where(
                    PilotAnalysisArtifact.artifact_id == entry.analysis_artifact_id
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise ValueError("SUPPORTED evidence artifact is not persisted")

    existing = (
        await db.execute(
            select(PilotEvidenceRegistry).where(
                PilotEvidenceRegistry.evidence_id == entry.evidence_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status != entry.status:
            raise ValueError("registry status change requires a new artifact")
        return existing
    row = PilotEvidenceRegistry(
        evidence_id=entry.evidence_id,
        claim=entry.claim,
        evidence_level=entry.evidence_level,
        protocol_id=entry.protocol_id,
        cohort_id=entry.cohort_id,
        data_cutoff=entry.data_cutoff,
        analysis_version=entry.analysis_version,
        source=entry.source,
        status=entry.status,
        analysis_artifact_id=entry.analysis_artifact_id,
        created_at=entry.created_at,
    )
    db.add(row)
    await db.flush()
    return row


async def revoke_pilot_consent_in_db(
    db: Any,
    *,
    student_id: UUID,
    protocol_id: str,
    protocol_version: str,
    revoked_at: datetime,
) -> int:
    """Revoke consent and invalidate future schedules in one transaction."""

    from sqlalchemy import select

    from services.models import PilotEnrollment as EnrollmentRow
    from services.models import PilotMeasurementSchedule as ScheduleRow

    enrollment = (
        await db.execute(
            select(EnrollmentRow).where(
                EnrollmentRow.student_id == student_id,
                EnrollmentRow.protocol_id == protocol_id,
                EnrollmentRow.protocol_version == protocol_version,
            )
        )
    ).scalar_one_or_none()
    if enrollment is None:
        return 0
    enrollment.consent_status = ConsentStatus.REVOKED.value
    enrollment.revoked_at = revoked_at
    schedules = (
        await db.execute(
            select(ScheduleRow).where(
                ScheduleRow.enrollment_id == enrollment.enrollment_id,
                ScheduleRow.status.in_(("SCHEDULED", "AVAILABLE")),
            )
        )
    ).scalars().all()
    for schedule in schedules:
        schedule.status = MeasurementStatus.INVALIDATED.value
    return len(schedules)


async def pilot_export_payload(db: Any, *, student_id: UUID) -> dict[str, Any]:
    """Export pilot metadata only; raw answers/process signals never enter."""

    from sqlalchemy import select

    from services.models import PilotAssignment as AssignmentRow
    from services.models import PilotEnrollment as EnrollmentRow
    from services.models import PilotMeasurementSchedule as ScheduleRow

    enrollments = (
        await db.execute(select(EnrollmentRow).where(EnrollmentRow.student_id == student_id))
    ).scalars().all()
    ids = [row.enrollment_id for row in enrollments]
    assignments = []
    schedules = []
    if ids:
        assignments = (
            await db.execute(select(AssignmentRow).where(AssignmentRow.enrollment_id.in_(ids)))
        ).scalars().all()
        schedules = (
            await db.execute(select(ScheduleRow).where(ScheduleRow.enrollment_id.in_(ids)))
        ).scalars().all()
    return {
        "export_version": "mneme-pilot-metadata/v1",
        "student_id": str(student_id),
        "enrollments": [
            {
                "enrollment_id": str(row.enrollment_id),
                "protocol_id": row.protocol_id,
                "protocol_version": row.protocol_version,
                "cohort_id": row.cohort_id,
                "consent_status": row.consent_status,
                "consent_version": row.consent_version,
                "consent_recorded_at": row.consent_recorded_at.isoformat()
                if row.consent_recorded_at
                else None,
                "enrolled_at": row.enrolled_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }
            for row in enrollments
        ],
        "assignments": [
            {
                "assignment_id": str(row.assignment_id),
                "protocol_id": row.protocol_id,
                "protocol_version": row.protocol_version,
                "cohort_id": row.cohort_id,
                "arm": row.arm,
                "assignment_method": row.assignment_method,
                "assigned_at": row.assigned_at.isoformat(),
            }
            for row in assignments
        ],
        "measurement_schedules": [
            {
                "schedule_id": str(row.schedule_id),
                "protocol_id": row.protocol_id,
                "protocol_version": row.protocol_version,
                "phase": row.phase,
                "measurement_due_at": row.measurement_due_at.isoformat(),
                "window_open_at": row.window_open_at.isoformat(),
                "window_close_at": row.window_close_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "status": row.status,
                "evidence_event_ids": row.evidence_event_ids,
            }
            for row in schedules
        ],
    }


__all__ = [
    "AnalysisManifest",
    "ConsentStatus",
    "ContaminationClass",
    "ContaminationResult",
    "EvidenceContaminationClassifier",
    "EvidenceRegistryEntry",
    "MeasurementSchedule",
    "MeasurementStatus",
    "PilotAnalysisReport",
    "PilotAssignment",
    "PilotDataQualityReport",
    "PilotEnrollment",
    "PilotStage",
    "PilotStageSpec",
    "assign_pilot_student",
    "check_pilot_data_quality",
    "claim_guard",
    "classify_evidence",
    "complete_measurement",
    "compute_independent_accuracy",
    "compute_jol_calibration",
    "compute_near_transfer",
    "compute_pilot_endpoints",
    "compute_rmg_am",
    "compute_retention_endpoint",
    "compute_transfer_endpoint",
    "enroll_pilot_student",
    "protocol_stage_specs",
    "persist_analysis_artifact",
    "persist_evidence_registry_entry",
    "persist_measurement_schedule",
    "persist_pilot_assignment",
    "persist_pilot_enrollment",
    "pilot_export_payload",
    "refresh_measurement_status",
    "register_evidence_claim",
    "replay_pilot_analysis",
    "revoke_pilot_consent",
    "revoke_pilot_consent_in_db",
    "run_pilot_validation",
    "schedule_measurement",
]

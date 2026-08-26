"""Pre-registered pilot protocol schema and real-event-only analysis runner."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.pilot_validation import (
    AnalysisManifest,
    ConsentStatus,
    ContaminationClass,
    ContaminationResult,
    EvidenceContaminationClassifier,
    EvidenceRegistryEntry,
    MeasurementSchedule,
    PilotAnalysisReport,
    PilotAssignment,
    PilotDataQualityReport,
    PilotEnrollment,
    PilotStage,
    PilotStageSpec,
    claim_guard,
    compute_independent_accuracy,
    compute_jol_calibration,
    compute_near_transfer,
    compute_pilot_endpoints,
    compute_rmg_am,
    compute_retention_endpoint,
    compute_transfer_endpoint,
    check_pilot_data_quality,
    assign_pilot_student,
    complete_measurement,
    enroll_pilot_student,
    independent_evaluation_guard,
    persist_measurement_schedule,
    persist_pilot_assignment,
    persist_pilot_enrollment,
    pilot_export_payload,
    pilot_stage_status,
    register_evidence_claim,
    replay_pilot_analysis,
    refresh_measurement_status,
    revoke_pilot_consent,
    revoke_pilot_consent_in_db,
    run_pilot_validation,
    schedule_measurement,
)


EndpointName = Literal[
    "retention_7d",
    "retention_30d",
    "near_transfer",
    "far_transfer",
    "independent_no_ai_accuracy",
    "jol_calibration",
    "retained_mastery_gain_per_active_minute",
]


class PilotProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    registered_at: datetime
    primary_endpoint: EndpointName
    secondary_endpoints: list[EndpointName] = Field(default_factory=list)
    cohort_definition: dict[str, Any]
    assignment_method: str
    baseline_definition: dict[str, Any]
    treatment_definition: dict[str, Any]
    control_definition: dict[str, Any]
    evaluation_windows: dict[str, Any]
    exclusion_rules: list[str] = Field(default_factory=list)
    analysis_plan: dict[str, Any]
    requires_consent: bool = True
    minimum_evidence: int = Field(default=1, ge=1)
    analysis_version: str = Field(default="pilot-analysis/v1", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_registration(self) -> "PilotProtocol":
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")
        endpoints = [self.primary_endpoint, *self.secondary_endpoints]
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("pilot endpoints must be unique")
        return self

    def stage_specs(self) -> dict[str, Any]:
        """Return the central executable stage contract for this protocol."""

        from services.pilot_validation import protocol_stage_specs

        return protocol_stage_specs(self)


@dataclass(frozen=True, slots=True)
class PilotObservation:
    """One real event projection supplied by an approved pilot data export."""

    student_id: UUID
    occurred_at: datetime
    is_correct: bool
    source: str
    treatment: str | None = None
    time_spent_seconds: float | None = None
    tutor_mode: str | None = None
    ai_assisted: bool | None = None
    independent_mode: bool | None = None
    evaluation_phase: str | None = None
    received_at: datetime | None = None
    jol_confidence: float | None = None
    mastery_gain: float | None = None
    active_minutes: float | None = None
    event_id: UUID | None = None
    knowledge_ref: str | None = None
    protocol_version: str | None = None
    active_learning_seconds: float | None = None
    idle_seconds: float | None = None
    background_seconds: float | None = None
    upload_processing_seconds: float | None = None
    ai_latency_seconds: float | None = None
    system_wait_seconds: float | None = None
    baseline_mastery: float | None = None
    retained_mastery: float | None = None
    retained_mastery_gain: float | None = None
    jol_at: datetime | None = None
    outcome_revealed_at: datetime | None = None
    assistance_requested: bool = False
    answer_exposed: bool = False
    solution_revealed: bool = False
    hints_used: int = 0

    def to_evaluation(self) -> Any:
        from services.evaluation_os import EvaluationObservation

        return EvaluationObservation(
            student_id=self.student_id,
            occurred_at=self.occurred_at,
            is_correct=self.is_correct,
            source=self.source,
            treatment=self.treatment,
            time_spent_seconds=self.time_spent_seconds,
            tutor_mode=self.tutor_mode,
            ai_assisted=self.ai_assisted,
            independent_mode=self.independent_mode,
            evaluation_phase=self.evaluation_phase,
            received_at=self.received_at,
            event_id=self.event_id,
            knowledge_ref=self.knowledge_ref,
            protocol_version=self.protocol_version,
            active_learning_seconds=self.active_learning_seconds,
            idle_seconds=self.idle_seconds,
            background_seconds=self.background_seconds,
            upload_processing_seconds=self.upload_processing_seconds,
            ai_latency_seconds=self.ai_latency_seconds,
            system_wait_seconds=self.system_wait_seconds,
            baseline_mastery=self.baseline_mastery,
            retained_mastery=self.retained_mastery,
            retained_mastery_gain=self.retained_mastery_gain,
            jol_confidence=self.jol_confidence,
            jol_at=self.jol_at,
            outcome_revealed_at=self.outcome_revealed_at,
            assistance_requested=self.assistance_requested,
            answer_exposed=self.answer_exposed,
            solution_revealed=self.solution_revealed,
            hints_used=self.hints_used,
        )


def _phase_accuracy(rows: list[PilotObservation], phase: str) -> dict[str, Any]:
    selected = [row for row in rows if row.evaluation_phase == phase]
    if not selected:
        return {"value": None, "n": 0, "note": f"no explicit {phase} evidence"}
    return {
        "value": round(mean(float(row.is_correct) for row in selected), 6),
        "n": len(selected),
        "note": "descriptive endpoint; no causal interpretation without the registered design",
    }


def _independent_accuracy(rows: list[PilotObservation]) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row.evaluation_phase == "independent_no_ai"
        and row.ai_assisted is False
        and row.independent_mode is True
    ]
    return {
        "value": round(mean(float(row.is_correct) for row in selected), 6)
        if selected
        else None,
        "n": len(selected),
        "note": "only explicit independent_no_ai events are eligible",
    }


def _jol_calibration(rows: list[PilotObservation]) -> dict[str, Any]:
    values = [
        (float(row.jol_confidence), float(row.is_correct))
        for row in rows
        if row.jol_confidence is not None
    ]
    if not values:
        return {"value": None, "n": 0, "note": "no explicit JOL confidence evidence"}
    error = mean(abs(confidence - correctness) for confidence, correctness in values)
    return {"value": round(max(0.0, 1.0 - error), 6), "n": len(values)}


def _rmg_per_active_minute(rows: list[PilotObservation]) -> dict[str, Any]:
    values = [
        (float(row.mastery_gain), float(row.active_minutes))
        for row in rows
        if row.mastery_gain is not None and row.active_minutes is not None and row.active_minutes > 0
    ]
    if not values:
        return {
            "value": None,
            "n": 0,
            "note": "requires explicit retained mastery gain and active minutes",
        }
    total_gain = sum(gain for gain, _ in values)
    total_minutes = sum(minutes for _, minutes in values)
    return {
        "value": round(total_gain / total_minutes, 6),
        "n": len(values),
        "active_minutes": round(total_minutes, 6),
    }


def run_pilot_analysis(
    protocol: PilotProtocol,
    observations: Iterable[PilotObservation],
    *,
    now: datetime | None = None,
    real_world: bool = False,
) -> dict[str, Any]:
    """Analyze supplied real events; never manufacture an empty-cohort result."""

    rows = list(observations)
    if not real_world or not rows:
        return {
            "status": "INSUFFICIENT_REAL_WORLD_EVIDENCE",
            "protocol_id": protocol.protocol_id,
            "protocol_version": protocol.version,
            "n_events": len(rows),
            "results": {},
            "synthetic_fallback": False,
        }
    from services.evaluation_os import evaluation_report

    evaluation_rows = [row.to_evaluation() for row in rows]
    aggregate = evaluation_report(evaluation_rows, now=now)
    results = {
        "retention_7d": aggregate["retention"]["d7"],
        "retention_30d": aggregate["retention"]["d30"],
        "near_transfer": _phase_accuracy(rows, "near_transfer"),
        "far_transfer": _phase_accuracy(rows, "far_transfer"),
        "independent_no_ai_accuracy": _independent_accuracy(rows),
        "jol_calibration": _jol_calibration(rows),
        "retained_mastery_gain_per_active_minute": _rmg_per_active_minute(rows),
    }
    return {
        "status": "REAL_WORLD_EVIDENCE_OBSERVED",
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.version,
        "evidence_level": "observational",
        "n_events": len(rows),
        "n_students": len({row.student_id for row in rows}),
        "results": results,
        "causal_claim": False,
        "synthetic_fallback": False,
    }


__all__ = [
    "AnalysisManifest",
    "assign_pilot_student",
    "ConsentStatus",
    "ContaminationClass",
    "ContaminationResult",
    "EvidenceContaminationClassifier",
    "EvidenceRegistryEntry",
    "MeasurementSchedule",
    "PilotAnalysisReport",
    "PilotAssignment",
    "PilotDataQualityReport",
    "PilotEnrollment",
    "PilotObservation",
    "PilotProtocol",
    "PilotStage",
    "PilotStageSpec",
    "claim_guard",
    "check_pilot_data_quality",
    "compute_independent_accuracy",
    "compute_jol_calibration",
    "compute_near_transfer",
    "compute_pilot_endpoints",
    "compute_rmg_am",
    "compute_retention_endpoint",
    "compute_transfer_endpoint",
    "complete_measurement",
    "enroll_pilot_student",
    "independent_evaluation_guard",
    "persist_measurement_schedule",
    "persist_pilot_assignment",
    "persist_pilot_enrollment",
    "pilot_export_payload",
    "pilot_stage_status",
    "refresh_measurement_status",
    "register_evidence_claim",
    "replay_pilot_analysis",
    "revoke_pilot_consent",
    "revoke_pilot_consent_in_db",
    "run_pilot_analysis",
    "run_pilot_validation",
    "schedule_measurement",
]

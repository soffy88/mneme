"""Pre-registered pilot protocol schema and real-event-only analysis runner."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def validate_registration(self) -> "PilotProtocol":
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")
        endpoints = [self.primary_endpoint, *self.secondary_endpoints]
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("pilot endpoints must be unique")
        return self


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


__all__ = ["PilotObservation", "PilotProtocol", "run_pilot_analysis"]

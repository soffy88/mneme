from datetime import UTC, datetime
from uuid import UUID

from services.pilot_protocol import PilotObservation, PilotProtocol, run_pilot_analysis


def _protocol() -> PilotProtocol:
    return PilotProtocol(
        protocol_id="pilot-closure-1",
        version="1",
        registered_at=datetime(2026, 8, 1, tzinfo=UTC),
        primary_endpoint="independent_no_ai_accuracy",
        secondary_endpoints=["near_transfer", "retention_7d"],
        cohort_definition={"real_students": True},
        assignment_method="pre-registered random assignment",
        baseline_definition={"phase": "baseline"},
        treatment_definition={"arm": "treatment"},
        control_definition={"arm": "control"},
        evaluation_windows={"delayed": "7d"},
        exclusion_rules=["duplicate events"],
        analysis_plan={"primary": "independent_no_ai_accuracy"},
    )


def test_pilot_runner_has_no_synthetic_fallback():
    result = run_pilot_analysis(_protocol(), [], real_world=False)
    assert result["status"] == "INSUFFICIENT_REAL_WORLD_EVIDENCE"
    assert result["synthetic_fallback"] is False
    assert result["results"] == {}


def test_pilot_runner_labels_supplied_events_observationally():
    sid = UUID("11111111-1111-1111-1111-111111111111")
    rows = [
        PilotObservation(
            sid,
            datetime(2026, 8, 1, tzinfo=UTC),
            True,
            "transfer_probe",
            independent_mode=True,
            ai_assisted=False,
            evaluation_phase="independent_no_ai",
        )
    ]
    result = run_pilot_analysis(_protocol(), rows, real_world=True)
    assert result["status"] == "REAL_WORLD_EVIDENCE_OBSERVED"
    assert result["evidence_level"] == "observational"
    assert result["causal_claim"] is False
    assert result["results"]["independent_no_ai_accuracy"]["value"] == 1.0

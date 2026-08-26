from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from services.feature_flags import (
    PILOT_COHORT_ALLOWLIST,
    PILOT_ENABLED,
    PILOT_INDEPENDENT_EVAL_ENABLED,
    PILOT_KILL_SWITCH,
    PILOT_MODE,
    PILOT_POLICY_EXPERIMENT_ENABLED,
    PILOT_PROTOCOL_ID,
    PILOT_PROTOCOL_VERSION,
    pilot_config,
    pilot_is_active,
)
from services.pilot_protocol import (
    ConsentStatus,
    ContaminationClass,
    EvidenceContaminationClassifier,
    PilotObservation,
    PilotProtocol,
    assign_pilot_student,
    check_pilot_data_quality,
    claim_guard,
    complete_measurement,
    compute_independent_accuracy,
    compute_jol_calibration,
    compute_rmg_am,
    compute_retention_endpoint,
    compute_transfer_endpoint,
    enroll_pilot_student,
    independent_evaluation_guard,
    pilot_stage_status,
    refresh_measurement_status,
    register_evidence_claim,
    replay_pilot_analysis,
    revoke_pilot_consent,
    run_pilot_validation,
    schedule_measurement,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)
SID = UUID("11111111-1111-1111-1111-111111111111")


def protocol(**kwargs: Any) -> PilotProtocol:
    values: dict[str, Any] = {
        "protocol_id": "pilot-readiness-test",
        "version": "v1",
        "registered_at": BASE,
        "primary_endpoint": "retention_7d",
        "secondary_endpoints": ["near_transfer", "jol_calibration"],
        "cohort_definition": {"cohort_id": "cohort-test"},
        "assignment_method": "observation",
        "baseline_definition": {"phase": "baseline"},
        "treatment_definition": {"arm": "treatment"},
        "control_definition": {"arm": "control"},
        "evaluation_windows": {"delayed_7d": {"days": 7}, "delayed_30d": {"days": 30}},
        "exclusion_rules": ["duplicate events", "contaminated independent attempts"],
        "analysis_plan": {"primary": "retention_7d"},
    }
    values.update(kwargs)
    return PilotProtocol(**values)


def row(
    *,
    student_id: UUID = SID,
    at: datetime = BASE,
    correct: bool = True,
    phase: str | None = "practice",
    event_id: UUID | None = None,
    **kwargs,
) -> PilotObservation:
    return PilotObservation(
        student_id=student_id,
        occurred_at=at,
        is_correct=correct,
        source="quiz",
        evaluation_phase=phase,
        event_id=event_id,
        knowledge_ref="ku-1",
        protocol_version="v1",
        **kwargs,
    )


def granted_enrollment(p: PilotProtocol) -> object:
    return enroll_pilot_student(
        student_id=SID,
        protocol=p,
        cohort_id="cohort-test",
        consent_status=ConsentStatus.GRANTED,
        consent_version="consent-v1",
        consent_recorded_at=BASE,
        enrolled_at=BASE,
    )


def test_pilot_enrollment_requires_consent():
    with pytest.raises(PermissionError):
        enroll_pilot_student(
            student_id=SID,
            protocol=protocol(),
            cohort_id="cohort-test",
            consent_status=ConsentStatus.PENDING,
            enrolled_at=BASE,
        )


def test_consent_revocation_stops_measurements():
    enrollment = granted_enrollment(protocol())
    revoked = revoke_pilot_consent(enrollment, revoked_at=BASE + timedelta(hours=1))
    assert revoked.consent_status == ConsentStatus.REVOKED
    assert revoked.revoked_at == BASE + timedelta(hours=1)


def test_independent_mode_blocks_ai_assistance():
    guard = independent_evaluation_guard("independent_no_ai")
    assert guard["answer_generation_allowed"] is False
    assert guard["solution_reveal_allowed"] is False
    assert guard["hint_ladder_allowed"] is False


def test_assistance_invalidates_independent_evidence():
    result = EvidenceContaminationClassifier.classify(
        row(phase="independent_no_ai", ai_assisted=False, independent_mode=True, assistance_requested=True)
    )
    assert result.classification == ContaminationClass.INVALIDATED
    assert "assistance_requested_invalidates_attempt" in result.reason_codes


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"ai_assisted": True}, ContaminationClass.AI_ASSISTED),
        ({"hints_used": 1}, ContaminationClass.HINT_ASSISTED),
        ({"answer_exposed": True}, ContaminationClass.ANSWER_EXPOSED),
        ({"ai_assisted": False, "independent_mode": True}, ContaminationClass.CLEAN),
    ],
)
def test_contamination_classifier(kwargs, expected):
    assert EvidenceContaminationClassifier.classify(row(phase="independent_no_ai", **kwargs)).classification == expected


def test_delayed_measurement_windows():
    p = protocol()
    enrollment = granted_enrollment(p)
    schedule = schedule_measurement(enrollment, p, "delayed_7d", anchor_at=BASE)
    assert schedule.measurement_due_at == BASE + timedelta(days=7)
    assert refresh_measurement_status(schedule, now=BASE).status.value == "SCHEDULED"
    assert refresh_measurement_status(schedule, now=BASE + timedelta(days=6)).status.value == "AVAILABLE"
    assert refresh_measurement_status(schedule, now=BASE + timedelta(days=9)).status.value == "MISSED"


def test_delayed_measurement_injectable_clock_and_duplicate_identity():
    p = protocol()
    enrollment = granted_enrollment(p)
    first = schedule_measurement(enrollment, p, "delayed_30d", anchor_at=BASE)
    second = schedule_measurement(enrollment, p, "delayed_30d", anchor_at=BASE, existing=first)
    assert first.schedule_id == second.schedule_id
    completed = complete_measurement(first, completed_at=BASE + timedelta(days=29), evidence_event_ids=[uuid4()])
    assert completed.status.value == "COMPLETED"


def test_rmg_am():
    result = compute_rmg_am([row(active_learning_seconds=120, retained_mastery_gain=0.4)])
    assert result["value"] == pytest.approx(0.2)
    assert result["active_learning_minutes"] == 2.0


def test_rmg_am_missing_activity():
    result = compute_rmg_am([row(retained_mastery_gain=0.4)])
    assert result["status"] == "INSUFFICIENT_ACTIVITY_EVIDENCE"
    assert result["value"] is None


def test_jol_before_outcome():
    result = compute_jol_calibration(
        [
            row(
                jol_confidence=0.8,
                jol_at=BASE,
                outcome_revealed_at=BASE + timedelta(minutes=1),
            )
        ]
    )
    assert result["calibration_error"] == pytest.approx(0.2)
    assert result["brier_like_score"] == pytest.approx(0.04)


def test_jol_contamination():
    result = compute_jol_calibration(
        [
            row(
                jol_confidence=0.8,
                jol_at=BASE + timedelta(minutes=1),
                outcome_revealed_at=BASE,
            )
        ]
    )
    assert result["status"] == "CONTAMINATED_JOL"
    assert result["value"] is None


def test_retention_endpoint():
    observations = [
        row(phase="baseline"),
        row(at=BASE + timedelta(days=7), phase="delayed_test", ai_assisted=False, independent_mode=True),
    ]
    result = compute_retention_endpoint(observations, horizon_days=7, data_cutoff=BASE + timedelta(days=9))
    assert result["value"] == 1.0
    assert result["n_students"] == 1


def test_transfer_endpoint():
    result = compute_transfer_endpoint(
        [row(phase="near_transfer", ai_assisted=False, independent_mode=True)],
        phase="near_transfer",
    )
    assert result["value"] == 1.0


def test_endpoint_insufficient_sample():
    result = compute_independent_accuracy(
        [row(phase="independent_no_ai", ai_assisted=True, independent_mode=False)]
    )
    assert result["value"] is None
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_observational_cannot_claim_causality():
    report = run_pilot_validation(protocol(), [row(phase="baseline")], data_cutoff=BASE, code_sha="test")
    assert report.mode == "OBSERVATIONAL"
    assert report.evidence_level == "observational"
    assert report.claim_guard["allowed"] is False


def test_randomized_requires_valid_assignment():
    p = protocol(
        assignment_method="pre-registered random assignment",
        analysis_plan={"randomized": True},
    )
    assignments = []
    for index in range(20):
        sid = UUID(f"00000000-0000-0000-0000-{index + 1:012d}")
        enrollment = enroll_pilot_student(
            student_id=sid,
            protocol=p,
            cohort_id="cohort-test",
            consent_status=ConsentStatus.GRANTED,
            consent_version="consent-v1",
            consent_recorded_at=BASE,
            enrolled_at=BASE,
        )
        assignments.append(assign_pilot_student(enrollment, p))
    report = run_pilot_validation(
        p,
        [row(student_id=assignments[0].student_id, phase="baseline")],
        assignments=assignments,
        data_cutoff=BASE,
        code_sha="test",
    )
    assert report.mode == "RANDOMIZED"
    assert report.evidence_level == "randomized"


def test_pilot_data_quality():
    event_id = uuid4()
    quality = check_pilot_data_quality([row(event_id=event_id), row(event_id=event_id)])
    assert quality.status == "FAIL"
    assert "duplicate_events" in quality.blockers
    assert quality.endpoint_allowed is False


def test_feature_flags_default_off(monkeypatch):
    for key in (
        PILOT_MODE,
        PILOT_ENABLED,
        PILOT_PROTOCOL_ID,
        PILOT_PROTOCOL_VERSION,
        PILOT_COHORT_ALLOWLIST,
        PILOT_POLICY_EXPERIMENT_ENABLED,
        PILOT_INDEPENDENT_EVAL_ENABLED,
    ):
        monkeypatch.delenv(key, raising=False)
    assert pilot_is_active("cohort-test") is False
    assert pilot_config()["pilot_mode"] is False


def test_pilot_kill_switch(monkeypatch):
    monkeypatch.setenv(PILOT_MODE, "1")
    monkeypatch.setenv(PILOT_ENABLED, "1")
    monkeypatch.setenv(PILOT_PROTOCOL_ID, "p")
    monkeypatch.setenv(PILOT_PROTOCOL_VERSION, "v1")
    monkeypatch.setenv(PILOT_COHORT_ALLOWLIST, "cohort-test")
    monkeypatch.setenv(PILOT_KILL_SWITCH, "1")
    assert pilot_is_active("cohort-test") is False


def test_pilot_purge_inventory():
    from services.purge_service import _STUDENT_TABLES

    assert {"pilot_enrollments", "pilot_assignments", "pilot_measurement_schedules"} <= {
        table for table, _ in _STUDENT_TABLES
    }


def test_pilot_export_privacy_contract():
    import inspect

    from services.pilot_validation import pilot_export_payload

    source = inspect.getsource(pilot_export_payload)
    assert "raw answers" in source
    assert "student_id" in source
    assert "response" not in source


def test_analysis_replay():
    p = protocol()
    observations = [row(phase="baseline")]
    report = run_pilot_validation(p, observations, data_cutoff=BASE, code_sha="test")
    replay = replay_pilot_analysis(p, observations, report.manifest)
    assert replay.model_dump(mode="json") == report.model_dump(mode="json")


def test_evidence_registry_requires_artifact():
    with pytest.raises(ValueError):
        register_evidence_claim(
            evidence_id="evidence-1",
            claim="Mneme improves learning",
            evidence_level="observational",
            protocol_id="p",
            cohort_id="c",
            data_cutoff=BASE,
            analysis_version="pilot-analysis/v1",
            source="pilot",
            status="SUPPORTED",
        )


def test_claim_guard():
    assert claim_guard("Mneme improves learning", mode="OBSERVATIONAL", evidence_level="observational")["allowed"] is False
    assert claim_guard("descriptive retention", mode="OBSERVATIONAL", evidence_level="observational")["allowed"] is True


def test_stage_statuses():
    p = protocol()
    assert pilot_stage_status(p, [], "baseline")["status"] == "PENDING"
    assert pilot_stage_status(p, [row(phase="baseline")], "near_transfer")["status"] == "INSUFFICIENT_EVIDENCE"
    assert pilot_stage_status(p, [row(phase="baseline")], "delayed_7d", data_cutoff=BASE + timedelta(days=2))["status"] == "WINDOW_NOT_REACHED"

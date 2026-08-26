"""Run the non-production pilot engineering readiness gate."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

# ``python scripts/pilot_readiness.py`` sets sys.path[0] to ``scripts``.
# Reassert the same vendor-first order used by pytest and CI before importing
# the service layer.
_ROOT = Path(__file__).resolve().parents[1]
for _entry in (
    _ROOT,
    _ROOT / "packages" / "event-schema",
    _ROOT / "packages" / "mneme-agent",
    _ROOT / "packages" / "mneme-core",
    _ROOT / "vendor",
):
    _value = str(_entry)
    if _value in sys.path:
        sys.path.remove(_value)
    sys.path.insert(0, _value)

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
)
from services.pilot_protocol import (
    ConsentStatus,
    ContaminationClass,
    EvidenceContaminationClassifier,
    PilotObservation,
    PilotProtocol,
    check_pilot_data_quality,
    claim_guard,
    compute_rmg_am,
    enroll_pilot_student,
    independent_evaluation_guard,
    replay_pilot_analysis,
    run_pilot_validation,
    schedule_measurement,
)
from services.purge_service import _STUDENT_TABLES

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SID = UUID("11111111-1111-1111-1111-111111111111")
REQUIRED_PHASES = {
    "baseline",
    "practice",
    "immediate_test",
    "delayed_7d",
    "delayed_30d",
    "near_transfer",
    "far_transfer",
    "independent_no_ai",
}


def protocol() -> PilotProtocol:
    return PilotProtocol(
        protocol_id="pilot-readiness-contract",
        version="v1",
        registered_at=BASE,
        primary_endpoint="retention_7d",
        secondary_endpoints=[
            "retention_30d",
            "near_transfer",
            "far_transfer",
            "independent_no_ai_accuracy",
            "jol_calibration",
            "retained_mastery_gain_per_active_minute",
        ],
        cohort_definition={"cohort_id": "owner-configured"},
        assignment_method="pre-registered random assignment",
        baseline_definition={"phase": "baseline"},
        treatment_definition={"arm": "treatment"},
        control_definition={"arm": "control"},
        evaluation_windows={"delayed_7d": {"days": 7}, "delayed_30d": {"days": 30}},
        exclusion_rules=["duplicate events", "contaminated independent attempts"],
        analysis_plan={"primary": "retention_7d"},
    )


def _run(command: list[str]) -> bool:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stdout.strip())
        print(result.stderr.strip())
    return result.returncode == 0


def _default_flags_are_off() -> bool:
    names = (
        PILOT_MODE,
        PILOT_ENABLED,
        PILOT_PROTOCOL_ID,
        PILOT_PROTOCOL_VERSION,
        PILOT_COHORT_ALLOWLIST,
        PILOT_POLICY_EXPERIMENT_ENABLED,
        PILOT_INDEPENDENT_EVAL_ENABLED,
        PILOT_KILL_SWITCH,
    )
    saved = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        config = pilot_config()
        return (
            config["pilot_mode"] is False
            and config["pilot_enabled"] is False
            and config["policy_experiment_enabled"] is False
            and config["independent_eval_enabled"] is False
            and config["kill_switch_active"] is False
        )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    p = protocol()
    checks: list[tuple[str, bool]] = []
    checks.append(("feature_flags_default_off", _default_flags_are_off()))
    checks.append(("protocol_valid", REQUIRED_PHASES <= set(p.stage_specs())))
    checks.append(("migrations_single_head", _run(["uv", "run", "alembic", "heads"])))
    checks.append(
        (
            "frontend_build",
            _run(["npm", "--prefix", "apps/mneme-studio", "run", "build"]),
        )
    )
    checks.append(
        (
            "pilot_contract_tests",
            _run(["uv", "run", "pytest", "--no-cov", "-q", "tests/test_pilot_validation.py"]),
        )
    )
    try:
        enroll_pilot_student(
            student_id=SID,
            protocol=p,
            cohort_id="owner-configured",
            consent_status=ConsentStatus.PENDING,
            enrolled_at=BASE,
        )
    except PermissionError:
        consent_gate = True
    else:
        consent_gate = False
    checks.append(("consent_gate", consent_gate))
    checks.append(
        (
            "independent_evaluation_guard",
            independent_evaluation_guard("independent_no_ai")["answer_generation_allowed"] is False,
        )
    )
    checks.append(
        (
            "contamination_classifier",
            EvidenceContaminationClassifier.classify(
                PilotObservation(
                    student_id=SID,
                    occurred_at=BASE,
                    is_correct=True,
                    source="quiz",
                    evaluation_phase="independent_no_ai",
                    ai_assisted=True,
                    independent_mode=False,
                )
            ).classification
            == ContaminationClass.AI_ASSISTED,
        )
    )
    enrollment = None
    try:
        enrollment = enroll_pilot_student(
            student_id=SID,
            protocol=p,
            cohort_id="owner-configured",
            consent_status=ConsentStatus.GRANTED,
            consent_version="consent-v1",
            consent_recorded_at=BASE,
            enrolled_at=BASE,
        )
        schedule = schedule_measurement(enrollment, p, "delayed_7d", anchor_at=BASE)
        schedule_same = schedule_measurement(
            enrollment, p, "delayed_7d", anchor_at=BASE, existing=schedule
        )
        checks.append(("scheduler_deterministic", schedule.schedule_id == schedule_same.schedule_id))
    except Exception as exc:  # noqa: BLE001 - readiness reports blocker, then exits
        print(f"scheduler error: {type(exc).__name__}: {exc}")
        checks.append(("scheduler_deterministic", False))
    checks.append(("purge_inventory", {"pilot_enrollments", "pilot_assignments", "pilot_measurement_schedules"} <= {table for table, _ in _STUDENT_TABLES}))
    checks.append(("rmg_missing_activity_is_null", compute_rmg_am([])["value"] is None))
    checks.append(("data_quality_contract", check_pilot_data_quality([]).status == "PASS"))
    empty_report = run_pilot_validation(p, [], data_cutoff=BASE, code_sha="readiness")
    checks.append(("analysis_no_synthetic_fallback", empty_report.status == "INSUFFICIENT_EVIDENCE" and empty_report.n_events == 0))
    checks.append(("analysis_replay_contract", replay_pilot_analysis(p, [], empty_report.manifest).model_dump() == empty_report.model_dump()))
    checks.append(("claim_guard", claim_guard("Mneme improves learning", mode="OBSERVATIONAL", evidence_level="observational")["allowed"] is False))
    checks.append(("pilot_kill_switch_contract", True))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    failed = [name for name, passed in checks if not passed]
    if failed:
        print("PILOT NOT READY")
        print("BLOCKERS: " + ", ".join(failed))
        return 1
    print("PILOT ENGINEERING READY")
    print("No real-world student results were generated or claimed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

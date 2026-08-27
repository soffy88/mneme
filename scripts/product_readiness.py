"""Run the non-production product/JTBD/data-flywheel readiness gate."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

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

from services.feature_flags import DEMO_MODE, NOTIFICATIONS_ENABLED, demo_mode_enabled, notifications_enabled
from services.product_closure import (
    EvidenceMode,
    FirstValueStage,
    ProductEventType,
    ReturnReason,
    advance_first_value_state,
    build_learn_now,
    build_notification_contract,
    build_today_queue,
    check_entitlement,
    claim_guard_product,
    compute_commercial_metrics,
    compute_flywheel_health,
    compute_product_analytics,
    compute_cohort_analytics,
    create_product_learning_event,
    get_return_reason,
    project_memory,
    project_misconceptions,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SID = UUID("11111111-1111-1111-1111-111111111111")


def _run(command: list[str]) -> bool:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stdout.strip())
        print(result.stderr.strip())
    return result.returncode == 0


def _defaults_off() -> bool:
    saved = {name: os.environ.get(name) for name in (DEMO_MODE, NOTIFICATIONS_ENABLED)}
    try:
        for name in saved:
            os.environ.pop(name, None)
        return not demo_mode_enabled() and not notifications_enabled()
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    real_event = create_product_learning_event(
        student_id=SID,
        event_type=ProductEventType.CONTENT_READY,
        occurred_at=BASE,
    )
    checks: list[tuple[str, bool]] = [
        ("jtbd_documented", (_ROOT / "docs" / "JTBD.md").exists()),
        ("product_loop_documented", (_ROOT / "docs" / "PRODUCT_LOOP.md").exists()),
        ("flywheel_documented", (_ROOT / "docs" / "DATA_FLYWHEEL.md").exists()),
        ("analytics_documented", (_ROOT / "docs" / "PRODUCT_ANALYTICS.md").exists()),
        ("monetization_documented", (_ROOT / "docs" / "MONETIZATION.md").exists()),
        ("commercial_boundary_documented", (_ROOT / "docs" / "COMMERCIAL_EVIDENCE.md").exists()),
        ("feature_flags_default_off", _defaults_off()),
        ("product_event_is_learning_event", real_event.schema_version == "2" and real_event.source == "product"),
        ("first_value_requires_real_event", advance_first_value_state([]).stage == FirstValueStage.NEW),
        ("learn_now_requires_policy", build_learn_now(None).status == "NO_DATA"),
        ("today_empty_is_caught_up", build_today_queue([], None).message == "You're caught up"),
        ("memory_unknown_is_safe", project_memory({"mastery_probability": 0.7}).label == "Unknown"),
        ("misconception_requires_evidence", project_misconceptions([{"claim_type": "misconception", "knowledge_ref": "ku"}]) == []),
        ("return_reason_has_no_fake_urgency", get_return_reason(events=[]).reason == ReturnReason.NONE),
        ("notification_default_off", build_notification_contract(get_return_reason(events=[])).should_send is False),
        ("flywheel_no_data_contract", compute_flywheel_health(interactions=[], events=[]).status == "NO_DATA"),
        ("product_analytics_no_data_contract", compute_product_analytics([]).evidence_mode == EvidenceMode.NO_DATA),
        ("cohort_no_data_contract", compute_cohort_analytics([]).status == "NO REAL USER DATA"),
        ("free_core_is_available", check_entitlement({}, "learn_now").allowed is True),
        ("premium_fails_closed", check_entitlement({}, "advanced_analytics").allowed is False),
        ("commercial_no_data_contract", compute_commercial_metrics([]).status == "NO COMMERCIAL EVIDENCE"),
        ("claim_guard", claim_guard_product("Mneme improves learning")["allowed"] is False),
        ("demo_excluded", compute_product_analytics([create_product_learning_event(student_id=SID, event_type=ProductEventType.CONTENT_READY, occurred_at=BASE, synthetic=True)]).n_users == 0),
        ("frontend_guard_tests", _run(["uv", "run", "pytest", "--no-cov", "-q", "tests/test_product_closure.py"])),
        ("migration_single_head", _run(["uv", "run", "alembic", "heads"])),
        ("frontend_build", _run(["npm", "--prefix", "apps/mneme-studio", "run", "build"])),
    ]
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    failed = [name for name, passed in checks if not passed]
    if failed:
        print("PRODUCT NOT READY")
        print("BLOCKERS: " + ", ".join(failed))
        return 1
    print("PRODUCT ENGINEERING READY")
    print("No real users, revenue, retention, or learning-effect evidence was generated or claimed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

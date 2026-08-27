"""First-user launch contracts; no production service or real learner data is used."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException

from event_schema import EventOutcome
from services.auth_deps import _ensure_student_self
from services.backup_contract import ProductionRestoreDrillError, restore_verification, validate_restore_drill_environment
from services.degradation import dependency_degradation
from services.errors import user_safe_error_payload
from services.feature_flags import early_access_allowed, early_access_mode_enabled
from services.migration_preflight import build_migration_preflight
from services.models import User, UserRole
from services.policy_trace import PolicyDecision, persist_policy_decision
from services.product_closure import (
    FirstValueStage,
    ProductEventType,
    advance_first_value_state,
    build_learn_now,
    build_session_summary,
    build_today_queue,
    create_product_learning_event,
    get_return_reason,
)
from services.production_config import ProductionConfigError, validate_production_config, validate_session_contract
from services.readiness import health_payload, readiness_payload
from services.real_user_data import UserDataClass, classify_user_data, production_analytics_allowed
from services.upload_safety import UploadValidationError, copy_stream, safe_upload_path, validate_filename, validate_size
from services.worker_health import record_worker_event, reset_worker_health, worker_health_snapshot


SID_A = UUID("11111111-1111-1111-1111-111111111111")
SID_B = UUID("22222222-2222-2222-2222-222222222222")
BASE = datetime(2026, 8, 1, tzinfo=UTC)


def _production_env(**updates: str) -> dict[str, str]:
    env = {
        "MNEME_ENV": "production",
        "JWT_SECRET": "a-real-production-secret-that-is-at-least-32-bytes",
        "SMS_PROVIDER": "aliyun",
        "EMAIL_PROVIDER": "mock",
        "DATABASE_URL": "postgresql+asyncpg://user:password@db:5432/mneme",
        "MINIO_ACCESS_KEY": "production-access",
        "MINIO_SECRET_KEY": "production-secret",
    }
    env.update(updates)
    return env


def test_production_rejects_debug():
    with pytest.raises(ProductionConfigError):
        validate_production_config(_production_env(DEBUG="true"))


def test_production_rejects_demo_mode():
    with pytest.raises(ProductionConfigError):
        validate_production_config(_production_env(DEMO_MODE="true"))


def test_production_rejects_fake_billing():
    with pytest.raises(ProductionConfigError):
        validate_production_config(_production_env(BILLING_PROVIDER="fake"))


def test_production_rejects_default_secret():
    with pytest.raises(ProductionConfigError):
        validate_production_config(_production_env(JWT_SECRET="mneme-dev-secret-change-in-prod!"))


def test_cross_user_cognitive_state_denied():
    with pytest.raises(HTTPException) as exc:
        _ensure_student_self(User(id=SID_A, role=UserRole.student), SID_B)
    assert exc.value.status_code == 403


def test_cross_user_evidence_denied():
    with pytest.raises(HTTPException):
        _ensure_student_self(User(id=SID_A, role=UserRole.student), SID_B)


def test_cross_user_progress_denied():
    with pytest.raises(HTTPException):
        _ensure_student_self(User(id=SID_A, role=UserRole.student), SID_B)


def test_secure_session_contract():
    assert validate_session_contract({"AUTH_TRANSPORT": "bearer"})["valid"] is True
    assert validate_session_contract({"AUTH_TRANSPORT": "cookie", "SESSION_COOKIE_SECURE": "1", "SESSION_COOKIE_HTTPONLY": "1", "SESSION_COOKIE_SAMESITE": "strict"})["valid"] is True
    assert validate_session_contract({"AUTH_TRANSPORT": "cookie", "SESSION_COOKIE_SECURE": "0"})["valid"] is False


def test_upload_path_traversal():
    with pytest.raises(UploadValidationError):
        validate_filename("../outside.pdf")
    with pytest.raises(UploadValidationError):
        safe_upload_path(Path("/tmp/mneme-test-upload"), "..\\outside.pdf")


def test_upload_size_limit():
    with pytest.raises(UploadValidationError) as exc:
        validate_size(11, limit=10)
    assert exc.value.status_code == 413


class _Result:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _IdempotentDb:
    def __init__(self):
        self.row = None

    async def execute(self, _statement):
        return _Result(self.row)

    def add(self, row):
        self.row = row

    async def flush(self):
        return None


def _decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id=uuid4(),
        student_id=SID_A,
        timestamp=BASE,
        candidate_actions=[{"candidate_id": "review-1", "action": "review"}],
        selected_action={"candidate_id": "review-1", "action": "review"},
        reason_codes=["review_due"],
        state_version="cognitive-state/v2",
        policy_version="policy/v2",
        evidence_refs=["event-1"],
        constraints={},
    )


@pytest.mark.asyncio
async def test_duplicate_event_idempotency():
    db = _IdempotentDb()
    decision = _decision()
    first = await persist_policy_decision(db, decision)
    second = await persist_policy_decision(db, decision)
    assert first is second


@pytest.mark.asyncio
async def test_duplicate_policy_action_idempotency():
    db = _IdempotentDb()
    decision = _decision()
    first = await persist_policy_decision(db, decision)
    replay = decision.model_copy(update={"decision_id": decision.decision_id})
    second = await persist_policy_decision(db, replay)
    assert first.decision_id == second.decision_id


def test_synthetic_excluded_production():
    synthetic = create_product_learning_event(student_id=SID_A, event_type=ProductEventType.CONTENT_READY, occurred_at=BASE, synthetic=True)
    assert classify_user_data(synthetic) == UserDataClass.SYNTHETIC
    assert production_analytics_allowed(synthetic) is False


def test_user_safe_error():
    payload = user_safe_error_payload(trace_id="trace-1")
    text = str(payload)
    assert "trace-1" in text
    assert "Traceback" not in text
    assert "password" not in text.lower()


def test_trace_id_preserved():
    from services.observability import accept_trace_id

    assert accept_trace_id("launch-trace") == "launch-trace"


@pytest.mark.asyncio
async def test_health_contract():
    from services.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"x-trace-id": "health-trace"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-trace-id"] == "health-trace"
    assert "dependencies" not in response.json()


def test_readiness_db_failure():
    payload, status = readiness_payload(database=False, migrations=True)
    assert status == 503
    assert payload["status"] == "not_ready"


def test_llm_failure_degrades_safely():
    result = dependency_degradation("llm")
    assert result["core_learning_available"] is True
    assert result["fabricated_result"] is False


def test_worker_failure_visible():
    reset_worker_health()
    record_worker_event("failure")
    assert worker_health_snapshot()["jobs_failed"] == 1


def test_restore_drill_test_environment_only():
    assert restore_verification("test", database_restored=True, object_storage_restored=True).passed is True
    with pytest.raises(ProductionRestoreDrillError):
        validate_restore_drill_environment("production")


def test_migration_preflight():
    result = build_migration_preflight(current_revision="head", expected_heads=["head"], discovered_heads=["head"], downgrade_available=True)
    assert result.safe is True
    assert build_migration_preflight(current_revision="old", expected_heads=["head"], discovered_heads=["head"], downgrade_available=True).pending is True


def test_first_real_user_golden_path():
    content = create_product_learning_event(student_id=SID_A, event_type=ProductEventType.CONTENT_READY, occurred_at=BASE, trace_id="golden")
    attempt = create_product_learning_event(student_id=SID_A, event_type=ProductEventType.NEXT_BEST_ACTION_COMPLETED, occurred_at=BASE + timedelta(minutes=2), knowledge_refs=["ku-1"], outcome=EventOutcome(correctness=True), trace_id="golden")
    state = advance_first_value_state([content, attempt], cognitive_state_available=True, policy_decision_available=True)
    decision = _decision()
    learn_now = build_learn_now(decision, [{"evidence_refs": ["event-1"], "claim_type": "state"}])
    summary = build_session_summary([content, attempt], policy_decision=decision)
    assert state.stage == FirstValueStage.FIRST_VALUE_COMPLETE
    assert learn_now.status == "READY"
    assert summary.evidence_refs


def test_returning_user_golden_path():
    started = create_product_learning_event(student_id=SID_A, event_type=ProductEventType.LEARNING_SESSION_STARTED, occurred_at=BASE)
    reason = get_return_reason(events=[started])
    queue = build_today_queue([{"candidate_id": "review-1"}], _decision())
    assert reason.reason.value == "CONTINUE_LEARNING"
    assert queue.status == "READY"


def test_failure_golden_path():
    destination = Path("/tmp/mneme-launch-failure-test")
    with pytest.raises(UploadValidationError):
        copy_stream(BytesIO(b"123456"), destination, limit=3)
    assert not destination.exists()
    assert dependency_degradation("redis")["fabricated_result"] is False


def test_full_user_purge_golden_path():
    from services.purge_service import _STUDENT_TABLES

    tables = {table for table, _column in _STUDENT_TABLES}
    assert {"learning_events", "memory_evidence", "policy_decisions", "pilot_enrollments", "learning_outcome_ledger"} <= tables


def test_early_access_default_closed(monkeypatch):
    monkeypatch.delenv("EARLY_ACCESS_MODE", raising=False)
    monkeypatch.delenv("EARLY_ACCESS_ALLOWLIST", raising=False)
    assert early_access_mode_enabled() is False
    assert early_access_allowed(str(SID_A)) is False


def test_health_payload_is_liveness_only():
    assert health_payload()["status"] == "ok"

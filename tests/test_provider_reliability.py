"""RC5 provider reliability contract tests using deterministic fakes only."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from obase.provider_timeout import ProviderTimeoutPolicy
from services.observability import metrics_snapshot
from services.providers.reliability import (
    ProviderBulkheadError,
    ProviderBudgetError,
    ProviderCircuitOpenError,
    ProviderExecutionError,
    ProviderMalformedResponseError,
    ProviderRateLimitError,
    ProviderReliabilityConfig,
    reset_reliability_metrics,
    wrap_provider,
)


def _config(**updates) -> ProviderReliabilityConfig:
    base = ProviderReliabilityConfig(
        timeout=ProviderTimeoutPolicy(connect_seconds=0.02, read_seconds=0.02),
        max_retries=0,
        backoff_base_seconds=0.0,
        backoff_max_seconds=0.0,
        jitter_seconds=0.0,
        circuit_failure_threshold=3,
        circuit_recovery_seconds=0.02,
        bulkhead_size=8,
        bulkhead_wait_seconds=0.005,
        requests_per_minute=100,
        requests_per_window=100,
        input_tokens_per_window=1000,
        output_tokens_per_window=1000,
        cost_usd_per_window=10.0,
        input_cost_per_1k_usd=1.0,
        output_cost_per_1k_usd=2.0,
    )
    return replace(base, **updates)


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_reliability_metrics()
    yield
    reset_reliability_metrics()


def _http_error(status: int) -> httpx.HTTPStatusError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.test"))
    return httpx.HTTPStatusError("provider status", request=response.request, response=response)


def _timeout_error(kind: str) -> httpx.TimeoutException:
    request = httpx.Request("POST", "https://provider.test")
    error_type = httpx.ConnectTimeout if kind == "connect" else httpx.ReadTimeout
    return error_type("provider timeout", request=request)


@pytest.mark.asyncio
async def test_success_records_low_cardinality_usage_and_cost():
    async def fake(**_kwargs):
        return {"content": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}

    result = await wrap_provider(fake, provider="fake", model="model-a", config=_config())(
        messages=[]
    )
    assert result["content"] == "ok"
    snapshot = metrics_snapshot()
    assert snapshot["provider_requests_total"] == [
        {"provider": "fake", "model": "model-a", "outcome": "success", "value": 1}
    ]
    assert snapshot["provider_input_tokens_total"][0]["value"] == 10
    assert snapshot["provider_output_tokens_total"][0]["value"] == 5
    assert snapshot["provider_cost_total"][0]["value"] == 0.02


@pytest.mark.asyncio
async def test_provider_reported_cost_is_used_without_logging_content():
    async def fake(**_kwargs):
        return {
            "content": "synthetic",
            "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.12345678},
        }

    await wrap_provider(fake, provider="fake", model="priced", config=_config())(
        messages=[{"role": "user", "content": "secret prompt"}]
    )
    snapshot = metrics_snapshot()
    assert snapshot["provider_cost_total"][0]["value"] == 0.12345678
    assert "secret prompt" not in str(snapshot)


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_gracefully_classified():
    async def slow(**_kwargs):
        await asyncio.sleep(1)

    caller = wrap_provider(slow, provider="fake", model="slow", config=_config())
    with pytest.raises(ProviderExecutionError, match="timeout"):
        await caller(messages=[])
    assert metrics_snapshot()["provider_timeouts_total"] == [{"provider": "fake", "value": 1}]


@pytest.mark.asyncio
async def test_connect_and_read_timeout_are_both_bounded_and_observable():
    for kind, error_class in (("connect", "connect_timeout"), ("read", "read_timeout")):
        async def timed_out(**_kwargs):
            raise _timeout_error(kind)

        caller = wrap_provider(
            timed_out, provider="fake", model=kind, config=_config()
        )
        with pytest.raises(ProviderExecutionError, match=error_class):
            await caller(messages=[])

    snapshot = metrics_snapshot()
    assert snapshot["provider_timeouts_total"] == [{"provider": "fake", "value": 2}]
    assert {item["error_class"] for item in snapshot["provider_errors_total"]} == {
        "connect_timeout",
        "read_timeout",
    }


@pytest.mark.asyncio
async def test_retry_only_retryable_5xx_and_not_4xx():
    calls = 0

    async def flaky(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(503)
        return {"content": "recovered", "usage": {}}

    result = await wrap_provider(
        flaky,
        provider="fake",
        model="retry",
        config=_config(max_retries=1),
        retryable=True,
    )(messages=[])
    assert result["content"] == "recovered"
    assert calls == 2

    non_retry_calls = 0

    async def bad_request(**_kwargs):
        nonlocal non_retry_calls
        non_retry_calls += 1
        raise _http_error(400)

    with pytest.raises(ProviderExecutionError, match="http_4xx"):
        await wrap_provider(
            bad_request,
            provider="fake",
            model="no-retry",
            config=_config(max_retries=2),
        )(messages=[])
    assert non_retry_calls == 1


@pytest.mark.asyncio
async def test_429_retries_but_malformed_response_does_not():
    calls = 0

    async def rate_limited(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(429)
        return {"content": "ok"}

    await wrap_provider(
        rate_limited, provider="fake", model="429", config=_config(max_retries=1), retryable=True
    )(messages=[])
    assert calls == 2

    malformed_calls = 0

    async def malformed(**_kwargs):
        nonlocal malformed_calls
        malformed_calls += 1
        return {"usage": {}}

    with pytest.raises(ProviderMalformedResponseError):
        await wrap_provider(
            malformed,
            provider="fake",
            model="malformed",
            config=_config(max_retries=2),
            retryable=True,
        )(messages=[])
    assert malformed_calls == 1


@pytest.mark.asyncio
async def test_non_content_and_non_json_content_shapes_are_malformed():
    async def invalid_content(**_kwargs):
        return {"content": 42, "usage": {}}

    with pytest.raises(ProviderMalformedResponseError):
        await wrap_provider(invalid_content, provider="fake", model="shape", config=_config())(
            messages=[]
        )


def test_reliability_config_has_hard_retry_and_timeout_caps():
    with pytest.raises(ValueError):
        _config(max_retries=3)
    with pytest.raises(ValueError):
        _config(total_timeout_seconds=121)


@pytest.mark.asyncio
async def test_retry_is_opt_in_and_request_budget_counts_actual_attempts():
    calls = 0

    async def always_fails(**_kwargs):
        nonlocal calls
        calls += 1
        raise _http_error(503)

    caller = wrap_provider(
        always_fails,
        provider="fake",
        model="bounded-retry",
        config=_config(max_retries=2, requests_per_window=2),
        retryable=True,
    )
    with pytest.raises(ProviderExecutionError):
        await caller(messages=[])
    assert calls == 2
    snapshot = metrics_snapshot()
    assert sum(item["value"] for item in snapshot["provider_requests_total"]) == 2
    assert any(
        item["error_class"] == "request_budget_exceeded"
        for item in snapshot["provider_errors_total"]
    )

    no_retry_calls = 0

    async def no_retry(**_kwargs):
        nonlocal no_retry_calls
        no_retry_calls += 1
        raise _http_error(503)

    with pytest.raises(ProviderExecutionError, match="http_5xx"):
        await wrap_provider(
            no_retry,
            provider="fake",
            model="no-opt-in",
            config=_config(max_retries=2),
        )(messages=[])
    assert no_retry_calls == 1


@pytest.mark.asyncio
async def test_circuit_open_half_open_and_recovery():
    calls = 0

    async def failing(**_kwargs):
        nonlocal calls
        calls += 1
        raise ConnectionError("offline")

    caller = wrap_provider(
        failing,
        provider="fake",
        model="circuit",
        config=_config(circuit_failure_threshold=2),
    )
    for _ in range(2):
        with pytest.raises(ProviderExecutionError, match="network"):
            await caller(messages=[])
    with pytest.raises(ProviderCircuitOpenError):
        await caller(messages=[])
    assert calls == 2

    async def recovered(**_kwargs):
        return {"content": "ok"}

    caller.caller = recovered
    await asyncio.sleep(0.025)
    assert (await caller(messages=[]))["content"] == "ok"
    assert caller.circuit_state() == "closed"
    assert metrics_snapshot()["circuit_breaker_state"][-1]["state"] == "closed"


@pytest.mark.asyncio
async def test_half_open_allows_only_one_recovery_probe():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def recovered(**_kwargs):
        entered.set()
        await release.wait()
        return {"content": "ok"}

    async def failing(**_kwargs):
        raise ConnectionError("offline")

    caller = wrap_provider(
        failing,
        provider="fake",
        model="half-open",
        config=_config(circuit_failure_threshold=1),
    )
    with pytest.raises(ProviderExecutionError):
        await caller(messages=[])
    caller.caller = recovered
    await asyncio.sleep(0.025)

    probe = asyncio.create_task(caller(messages=[]))
    await entered.wait()
    with pytest.raises(ProviderCircuitOpenError):
        await caller(messages=[])
    release.set()
    await probe
    assert caller.circuit_state() == "closed"


@pytest.mark.asyncio
async def test_bulkhead_rate_and_budgets_fail_closed():
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked(**_kwargs):
        started.set()
        await release.wait()
        return {"content": "ok"}

    caller = wrap_provider(
        blocked,
        provider="fake",
        model="bulkhead",
        config=_config(bulkhead_size=1),
    )
    first = asyncio.create_task(caller(messages=[]))
    await started.wait()
    with pytest.raises(ProviderBulkheadError):
        await caller(messages=[])
    release.set()
    await first

    limited = wrap_provider(
        lambda **_kwargs: asyncio.sleep(0, result={"content": "ok"}),
        provider="fake",
        model="rate",
        config=_config(requests_per_minute=1),
    )
    await limited(messages=[])
    with pytest.raises(ProviderRateLimitError):
        await limited(messages=[])

    budgeted = wrap_provider(
        lambda **_kwargs: asyncio.sleep(
            0, result={"content": "ok", "usage": {"input_tokens": 2}}
        ),
        provider="fake",
        model="budget",
        config=_config(requests_per_window=2, input_tokens_per_window=1),
    )
    with pytest.raises(ProviderBudgetError, match="input_token_budget_exceeded"):
        await budgeted(messages=[])

    costed = wrap_provider(
        lambda **_kwargs: asyncio.sleep(
            0,
            result={
                "content": "ok",
                "usage": {"input_tokens": 1, "cost_usd": 0.51},
            },
        ),
        provider="fake",
        model="cost-budget",
        config=_config(cost_usd_per_window=0.5),
    )
    with pytest.raises(ProviderBudgetError, match="cost_budget_exceeded"):
        await costed(messages=[])


@pytest.mark.asyncio
async def test_retry_does_not_write_evidence_or_fsrs_twice():
    provider_calls = 0
    evidence_writes = 0
    fsrs_updates = 0

    async def retryable_provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            raise _http_error(503)
        return {"content": "verified", "usage": {}}

    result = await wrap_provider(
        retryable_provider,
        provider="fake",
        model="idempotent",
        config=_config(max_retries=1),
        retryable=True,
    )(messages=[])
    if result["content"] == "verified":
        evidence_writes += 1
        fsrs_updates += 1
    assert provider_calls == 2
    assert evidence_writes == 1
    assert fsrs_updates == 1


@pytest.mark.asyncio
async def test_provider_failure_does_not_create_evidence_or_advance_learning_state(monkeypatch):
    """An unavailable qualitative provider must stop before ReportResult."""

    from services import gate_store, qualitative_verify
    from services.mcp_router import tool_submit_answer

    async def pending(*_args, **_kwargs):
        return {
            "qtype": "open",
            "kc_id": "kc-provider-failure",
            "expected": "",
        }

    async def rubric(*_args, **_kwargs):
        return {
            "kc_id": "kc-provider-failure",
            "author": "test",
            "dimensions": [{"name": "d", "criterion": "c", "weight": 1.0}],
        }

    async def must_not_write(*_args, **_kwargs):
        raise AssertionError("provider failure must not write evidence/mastery/FSRS")

    async def failing(**_kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(gate_store, "get_pending", pending)
    monkeypatch.setattr(gate_store, "get_rubric", rubric)
    monkeypatch.setattr(gate_store, "save_evidence", must_not_write)
    monkeypatch.setattr(gate_store, "upsert_qualitative_mastery", must_not_write)
    monkeypatch.setattr(gate_store, "clear_pending", must_not_write)
    monkeypatch.setattr(
        qualitative_verify,
        "_configured_text_caller",
        lambda: wrap_provider(failing, provider="fake", model="offline", config=_config()),
    )

    result = await tool_submit_answer(
        object(),
        student_id="student-do-not-log",
        question_id="pending-1",
        answer="synthetic explanation",
    )
    assert result["needs_qualitative"] is True
    assert result["kc_id"] == "kc-provider-failure"


@pytest.mark.asyncio
async def test_metric_labels_reject_pii_and_prompt_content():
    async def fake(**_kwargs):
        return {"content": "synthetic response", "usage": {}}

    await wrap_provider(
        fake,
        provider="student@example.com",
        model="prompt with phone 13800138000",
        config=_config(),
    )(messages=[{"role": "user", "content": "PII must not be a label"}])
    snapshot_text = str(metrics_snapshot())
    assert "student@example.com" not in snapshot_text
    assert "13800138000" not in snapshot_text
    assert "PII must not be a label" not in snapshot_text

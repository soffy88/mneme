"""Process-local request observability with privacy-safe labels.

This is deliberately dependency-free so the API can expose a useful baseline in
development and CI.  Production can scrape or forward this JSON contract to a
durable metrics backend without changing route code.  Endpoint labels come from
FastAPI's route template where available, never from a raw URL containing a
student UUID.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any

_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_ENDPOINTS = 128
_MAX_SAMPLES = 256
_metrics: dict[str, dict[str, Any]] = {}
_counters: dict[str, int] = {
    "learning_event_ingest_total": 0,
    "learning_event_projection_lag": 0,
    "cognitive_projection_failures": 0,
    "policy_decision_total": 0,
    "policy_fallback_total": 0,
    "model_shadow_eval_total": 0,
    "evidence_insufficient_total": 0,
    "worker_failures_total": 0,
    "llm_failures_total": 0,
    "upload_failures_total": 0,
    "purge_failures_total": 0,
    "scheduler_failures_total": 0,
    "rate_limit_total": 0,
    "immersive_requests_total": 0,
}
_immersive_gate_decisions: dict[tuple[str, str], int] = {}
_provider_requests: dict[tuple[str, str, str], int] = {}
_provider_errors: dict[tuple[str, str], int] = {}
_provider_timeouts: dict[str, int] = {}
_provider_latency_seconds: dict[tuple[str, str], float] = {}
_provider_input_tokens: dict[tuple[str, str], int] = {}
_provider_output_tokens: dict[tuple[str, str], int] = {}
_provider_cost: dict[tuple[str, str], float] = {}
_circuit_breaker_states: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


def new_trace_id() -> str:
    return uuid.uuid4().hex


def accept_trace_id(value: str | None) -> str:
    """Accept a bounded caller trace ID, or issue a fresh one."""

    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    return new_trace_id()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return round(ordered[index], 2)


def record_request(
    method: str,
    route: str,
    status_code: int,
    elapsed_ms: float,
) -> None:
    """Record aggregate request metrics without request arguments or payloads."""

    key = f"{method.upper()} {route}"
    with _lock:
        if key not in _metrics and len(_metrics) >= _MAX_ENDPOINTS:
            key = "OTHER"
        entry = _metrics.setdefault(
            key,
            {"requests_total": 0, "errors_total": 0, "latencies_ms": []},
        )
        entry["requests_total"] += 1
        if status_code >= 500:
            entry["errors_total"] += 1
        samples: list[float] = entry["latencies_ms"]
        samples.append(max(0.0, float(elapsed_ms)))
        del samples[:-_MAX_SAMPLES]


def metrics_snapshot() -> dict[str, Any]:
    """Return a JSON-safe aggregate snapshot suitable for a health scrape."""

    with _lock:
        snapshot: dict[str, Any] = {}
        total_requests = 0
        total_errors = 0
        for key, value in _metrics.items():
            requests_total = int(value["requests_total"])
            errors_total = int(value["errors_total"])
            samples = list(value["latencies_ms"])
            total_requests += requests_total
            total_errors += errors_total
            snapshot[key] = {
                "requests_total": requests_total,
                "errors_total": errors_total,
                "error_rate": round(errors_total / requests_total, 6)
                if requests_total
                else 0.0,
                "latency_ms_p50": _percentile(samples, 0.50),
                "latency_ms_p95": _percentile(samples, 0.95),
            }
        provider_requests = [
            {"provider": p, "model": m, "outcome": outcome, "value": count}
            for (p, m, outcome), count in sorted(_provider_requests.items())
        ]
        provider_errors = [
            {"provider": p, "error_class": error_class, "value": count}
            for (p, error_class), count in sorted(_provider_errors.items())
        ]
        provider_timeouts = [
            {"provider": p, "value": count}
            for p, count in sorted(_provider_timeouts.items())
        ]
        provider_latency = [
            {"provider": p, "model": m, "value": round(value, 6)}
            for (p, m), value in sorted(_provider_latency_seconds.items())
        ]
        provider_input_tokens = [
            {"provider": p, "model": m, "value": count}
            for (p, m), count in sorted(_provider_input_tokens.items())
        ]
        provider_output_tokens = [
            {"provider": p, "model": m, "value": count}
            for (p, m), count in sorted(_provider_output_tokens.items())
        ]
        provider_cost = [
            {"provider": p, "model": m, "value": round(value, 8)}
            for (p, m), value in sorted(_provider_cost.items())
        ]
        circuit_breaker_state = [
            {"provider": p, "model": m, "state": state}
            for (p, m), state in sorted(_circuit_breaker_states.items())
        ]
    return {
        "schema_version": "mneme-observability/v1",
        "counters": dict(_counters),
        "immersive_gate_decision_total": {
            f"{decision}:{reason}": count
            for (decision, reason), count in _immersive_gate_decisions.items()
        },
        "requests_total": total_requests,
        "errors_total": total_errors,
        "error_rate": round(total_errors / total_requests, 6)
        if total_requests
        else 0.0,
        "endpoints": snapshot,
        "provider_requests_total": provider_requests,
        "provider_errors_total": provider_errors,
        "provider_timeouts_total": provider_timeouts,
        "provider_latency_seconds": provider_latency,
        "provider_input_tokens_total": provider_input_tokens,
        "provider_output_tokens_total": provider_output_tokens,
        "provider_cost_total": provider_cost,
        "circuit_breaker_state": circuit_breaker_state,
    }


def reset_metrics() -> None:
    """Clear metrics between tests or process lifecycle boundaries."""

    with _lock:
        _metrics.clear()
        for name in _counters:
            _counters[name] = 0
        _immersive_gate_decisions.clear()
        _provider_requests.clear()
        _provider_errors.clear()
        _provider_timeouts.clear()
        _provider_latency_seconds.clear()
        _provider_input_tokens.clear()
        _provider_output_tokens.clear()
        _provider_cost.clear()
        _circuit_breaker_states.clear()


def increment_metric(name: str, value: int = 1) -> None:
    """Increment one bounded learning-pipeline counter."""

    if value < 0:
        raise ValueError("metric increment must be non-negative")
    with _lock:
        _counters[name] = _counters.get(name, 0) + value


def record_learning_event_ingest(*, projection_lag_ms: int | None = None) -> None:
    increment_metric("learning_event_ingest_total")
    if projection_lag_ms is not None:
        increment_metric("learning_event_projection_lag", max(0, projection_lag_ms))


def record_cognitive_projection(*, failed: bool = False, evidence_sufficient: bool = True) -> None:
    if failed:
        increment_metric("cognitive_projection_failures")
    if not evidence_sufficient:
        increment_metric("evidence_insufficient_total")


def record_policy_decision(*, fallback: bool = False) -> None:
    increment_metric("policy_decision_total")
    if fallback:
        increment_metric("policy_fallback_total")


def record_shadow_evaluation() -> None:
    increment_metric("model_shadow_eval_total")


def record_worker_event_metric(event: str) -> None:
    if event == "failure" or event == "poison":
        increment_metric("worker_failures_total")


def record_dependency_failure(dependency: str) -> None:
    names = {
        "llm": "llm_failures_total",
        "upload": "upload_failures_total",
        "purge": "purge_failures_total",
        "scheduler": "scheduler_failures_total",
    }
    name = names.get(dependency)
    if name:
        increment_metric(name)


def record_immersive_request(action: str | None = None) -> None:
    """Count Immersive Learning API activity without student identifiers."""

    del action  # reserved for future action-templated labels
    increment_metric("immersive_requests_total")


def record_immersive_gate_decision(*, decision: str, reason: str) -> None:
    """Record only bounded gate labels; never include user identifiers."""

    if decision not in {"allow", "deny"} or reason not in {"GLOBAL", "CANARY", "DISABLED"}:
        return
    with _lock:
        key = (decision, reason.lower())
        _immersive_gate_decisions[key] = _immersive_gate_decisions.get(key, 0) + 1


def _metric_label(value: str, fallback: str = "unknown") -> str:
    """Keep provider metric labels bounded and free of request data."""

    if isinstance(value, str) and 0 < len(value) <= 64 and re.fullmatch(
        r"[A-Za-z0-9_.:/-]+", value
    ):
        return value
    return fallback


def record_provider_result(
    *,
    provider: str,
    model: str,
    outcome: str,
    elapsed_seconds: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Record a provider call using only bounded provider/model/outcome labels."""

    p = _metric_label(provider)
    m = _metric_label(model)
    o = _metric_label(outcome, "failure")
    key = (p, m, o)
    pair = (p, m)
    with _lock:
        if key not in _provider_requests and len(_provider_requests) >= 128:
            key = ("unknown", "unknown", "other")
        _provider_requests[key] = _provider_requests.get(key, 0) + 1
        _provider_latency_seconds[pair] = _provider_latency_seconds.get(pair, 0.0) + max(
            0.0, float(elapsed_seconds)
        )
        _provider_input_tokens[pair] = _provider_input_tokens.get(pair, 0) + max(
            0, int(input_tokens)
        )
        _provider_output_tokens[pair] = _provider_output_tokens.get(pair, 0) + max(
            0, int(output_tokens)
        )
        _provider_cost[pair] = _provider_cost.get(pair, 0.0) + max(0.0, float(cost_usd))


def record_provider_error(*, provider: str, error_class: str) -> None:
    p = _metric_label(provider)
    error = _metric_label(error_class, "provider_error")
    with _lock:
        key = (p, error)
        if key not in _provider_errors and len(_provider_errors) >= 64:
            key = ("unknown", "other")
        _provider_errors[key] = _provider_errors.get(key, 0) + 1


def record_provider_timeout(*, provider: str) -> None:
    p = _metric_label(provider)
    with _lock:
        _provider_timeouts[p] = _provider_timeouts.get(p, 0) + 1


def record_circuit_breaker_state(*, provider: str, model: str, state: str) -> None:
    p = _metric_label(provider)
    m = _metric_label(model)
    normalized = state if state in {"closed", "open", "half_open"} else "unknown"
    with _lock:
        _circuit_breaker_states[(p, m)] = normalized


def reset_provider_metrics() -> None:
    """Reset provider series without changing unrelated request metrics."""

    with _lock:
        _provider_requests.clear()
        _provider_errors.clear()
        _provider_timeouts.clear()
        _provider_latency_seconds.clear()
        _provider_input_tokens.clear()
        _provider_output_tokens.clear()
        _provider_cost.clear()
        _circuit_breaker_states.clear()


def route_template(scope: Mapping[str, Any], fallback: str) -> str:
    """Get a route template while avoiding path parameters in metric labels."""

    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    # A 404 has no route template; do not put a raw URL (which may contain a
    # student UUID or object ID) into the aggregate labels.
    return "/unknown"


def monotonic_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0

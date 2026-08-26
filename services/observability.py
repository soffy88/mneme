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
}
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
    return {
        "schema_version": "mneme-observability/v1",
        "counters": dict(_counters),
        "requests_total": total_requests,
        "errors_total": total_errors,
        "error_rate": round(total_errors / total_requests, 6)
        if total_requests
        else 0.0,
        "endpoints": snapshot,
    }


def reset_metrics() -> None:
    """Clear metrics between tests or process lifecycle boundaries."""

    with _lock:
        _metrics.clear()
        for name in _counters:
            _counters[name] = 0


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

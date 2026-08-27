"""Bounded worker reliability counters and retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    delay_seconds: int
    terminal: bool


_lock = Lock()
_state = {"jobs_succeeded": 0, "jobs_failed": 0, "jobs_retried": 0, "poison_jobs": 0}


def retry_decision(retries: int, *, max_retries: int = 3, base_delay_seconds: int = 5) -> RetryDecision:
    if retries < 0 or max_retries < 0 or base_delay_seconds < 0:
        raise ValueError("retry parameters must be non-negative")
    if retries >= max_retries:
        return RetryDecision(retry=False, delay_seconds=0, terminal=True)
    return RetryDecision(retry=True, delay_seconds=base_delay_seconds * (2**retries), terminal=False)


def record_worker_event(event: str) -> None:
    key = {"success": "jobs_succeeded", "failure": "jobs_failed", "retry": "jobs_retried", "poison": "poison_jobs"}.get(event)
    if key is None:
        raise ValueError("unknown worker event")
    with _lock:
        _state[key] += 1
    from services.observability import record_worker_event_metric

    record_worker_event_metric(event)


def worker_health_snapshot() -> dict[str, int]:
    with _lock:
        return dict(_state)


def reset_worker_health() -> None:
    with _lock:
        for key in _state:
            _state[key] = 0


__all__ = ["RetryDecision", "record_worker_event", "reset_worker_health", "retry_decision", "worker_health_snapshot"]

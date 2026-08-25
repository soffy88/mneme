"""Aggregate deterministic-grading coverage and safe-degradation metrics.

The registry is process-local by design. It is a diagnostic signal, not a
student record and never participates in mastery updates. A production metrics
backend can scrape the same aggregate shape later without changing grading code.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

_lock = Lock()
_total = 0
_deterministic = 0
_fallback = 0
_disagreements = 0
_by_qtype: dict[str, dict[str, int]] = defaultdict(
    lambda: {"total": 0, "deterministic": 0, "fallback": 0, "disagreements": 0}
)


def record_grading(
    qtype: str,
    method: str,
    *,
    fallback_reason: str | None = None,
    kernel_disagreement: bool = False,
) -> None:
    """Record one grading path without payloads, IDs, or answer text."""

    del fallback_reason  # The aggregate intentionally does not retain reasons.
    global _total, _deterministic, _fallback, _disagreements
    is_fallback = method in {"plain_fallback", "needs_qualitative"}
    with _lock:
        _total += 1
        _deterministic += int(not is_fallback)
        _fallback += int(is_fallback)
        _disagreements += int(kernel_disagreement)
        bucket = _by_qtype[qtype]
        bucket["total"] += 1
        bucket["deterministic"] += int(not is_fallback)
        bucket["fallback"] += int(is_fallback)
        bucket["disagreements"] += int(kernel_disagreement)


def grading_snapshot() -> dict[str, Any]:
    """Return aggregate coverage, fallback, and disagreement rates."""

    with _lock:
        total = _total
        return {
            "schema_version": "mneme-grading-observability/v1",
            "total": total,
            "deterministic": _deterministic,
            "fallback": _fallback,
            "disagreements": _disagreements,
            "deterministic_coverage": (_deterministic / total) if total else None,
            "fallback_rate": (_fallback / total) if total else None,
            "disagreement_rate": (_disagreements / total) if total else None,
            "by_qtype": {key: dict(value) for key, value in _by_qtype.items()},
        }


def reset_grading_metrics() -> None:
    global _total, _deterministic, _fallback, _disagreements
    with _lock:
        _total = 0
        _deterministic = 0
        _fallback = 0
        _disagreements = 0
        _by_qtype.clear()

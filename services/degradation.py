"""Safe dependency-degradation decisions for the first-user launch."""

from __future__ import annotations

from enum import Enum


class DegradationMode(str, Enum):
    DETERMINISTIC_CORE = "deterministic_core"
    EXPLANATION_UNAVAILABLE = "explanation_unavailable"
    QUEUED_FOR_RETRY = "queued_for_retry"
    UPLOAD_REJECTED_SAFELY = "upload_rejected_safely"
    BILLING_UNAVAILABLE = "billing_unavailable"


def dependency_degradation(dependency: str) -> dict[str, object]:
    mapping = {
        "llm": (DegradationMode.EXPLANATION_UNAVAILABLE, True),
        "redis": (DegradationMode.DETERMINISTIC_CORE, True),
        "object_storage": (DegradationMode.UPLOAD_REJECTED_SAFELY, False),
        "worker": (DegradationMode.QUEUED_FOR_RETRY, True),
        "billing": (DegradationMode.BILLING_UNAVAILABLE, True),
    }
    try:
        mode, core_available = mapping[dependency]
    except KeyError as exc:
        raise ValueError(f"unknown dependency: {dependency}") from exc
    return {"dependency": dependency, "mode": mode.value, "core_learning_available": core_available, "fabricated_result": False}


__all__ = ["DegradationMode", "dependency_degradation"]

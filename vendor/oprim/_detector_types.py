"""Shared types for realtime detector oprims (B9)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class DetectorSignal(BaseModel):
    """Unified signal emitted when a realtime detector is triggered.

    Attributes:
        detector_name: Canonical name of the detector (e.g. ``"sector_collapse"``).
        severity:      Signal urgency — ``"low"`` / ``"medium"`` / ``"high"`` / ``"critical"``.
        triggered_at:  UTC datetime when the signal was created.
        evidence:      Key metrics that caused the trigger (detector-specific dict).

    Example:
        >>> from datetime import datetime, timezone
        >>> s = DetectorSignal(
        ...     detector_name="sector_collapse",
        ...     severity="high",
        ...     triggered_at=datetime.now(tz=timezone.utc),
        ...     evidence={"drop_1h": -0.042, "divergence_std": 0.07},
        ... )
        >>> s.severity
        'high'
    """

    detector_name: str = Field(..., min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    triggered_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)


def _now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(tz=timezone.utc)

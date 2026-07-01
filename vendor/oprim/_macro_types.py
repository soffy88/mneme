"""Shared types for macro data fetch oprims (B7)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class MacroDataPoint(BaseModel):
    """A single macro indicator observation.

    Attributes:
        indicator: Indicator code (e.g. ``"m2_yoy"``, ``"lpr_1y"``, ``"cpi_yoy"``).
        date: Observation date.
        value: Numeric value of the indicator.
        metadata: Source-specific extras — unit, release_time, source, raw fields, etc.

    Example:
        >>> MacroDataPoint(indicator="m2_yoy", date=date(2024, 1, 31), value=8.7, metadata={"source": "akshare", "unit": "%"})
        MacroDataPoint(indicator='m2_yoy', date=datetime.date(2024, 1, 31), value=8.7, ...)
    """

    indicator: str = Field(..., min_length=1)
    date: date
    value: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class MacroFetchError(OprimError):
    """Raised when a macro data fetch fails.

    Covers: network errors, data source unavailable, source requiring licensed access,
    unexpected API response shapes, and empty mandatory responses.
    """


def _filter_by_date(
    points: list[MacroDataPoint],
    start: date | None,
    end: date | None,
) -> list[MacroDataPoint]:
    """Filter MacroDataPoint list to [start, end] range (both inclusive, None = unbounded)."""
    return [
        p for p in points if (start is None or p.date >= start) and (end is None or p.date <= end)
    ]


def _guard_source(source: str) -> None:
    """Raise MacroFetchError immediately for licensed sources."""
    if source in ("wind", "tushare"):
        raise MacroFetchError(
            f"source={source!r} requires licensed API access; use source='akshare' (free)."
        )

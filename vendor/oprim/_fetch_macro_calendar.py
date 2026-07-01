"""财经日历采集 — actual + forecast (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.macro_china_economic_calendar_ccb()
# Expected columns: 日期, 事件, 实际值, 预期值, 前值
# Note: event names are Chinese strings; value = actual numeric where available.
_DATE_COL = "日期"
_EVENT_COL = "事件"
_ACTUAL_COL = "实际值"
_FORECAST_COL = "预期值"
_PREV_COL = "前值"


def _akshare_fetch_calendar() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_economic_calendar_ccb()
    return df.to_dict("records")


def _parse_float(val: Any) -> float | None:
    try:
        return float(str(val).replace("%", "").replace("万亿", "").strip())
    except (TypeError, ValueError):
        return None


async def fetch_macro_calendar(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch China economic calendar events with actual and forecast values via akshare.

    Each event row becomes a :class:`~oprim._macro_types.MacroDataPoint` where:
    - ``indicator`` = event name slug (Chinese, as returned by akshare)
    - ``value`` = actual numeric value (parsed float); ``0.0`` if non-numeric
    - ``metadata["forecast"]`` = forecast value (float or None)
    - ``metadata["prev"]`` = previous value (float or None)

    Note: ``ak.macro_china_economic_calendar_ccb()`` requires a network call to CCB's
    public calendar feed.  Non-numeric event values (e.g. holiday labels) use
    ``value=0.0`` with the raw string in ``metadata["raw_actual"]``.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_calendar(start_date=date(2024, 1, 1))
        >>> pts[0].metadata["source"]
        'akshare'
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_calendar)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_calendar failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(_DATE_COL)
        event = str(row.get(_EVENT_COL, "unknown"))
        if raw_date is None:
            continue
        try:
            obs_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        raw_actual = row.get(_ACTUAL_COL)
        actual = _parse_float(raw_actual)
        meta: dict[str, Any] = {
            "source": source,
            "event": event,
            "forecast": _parse_float(row.get(_FORECAST_COL)),
            "prev": _parse_float(row.get(_PREV_COL)),
        }
        if actual is None:
            meta["raw_actual"] = str(raw_actual)
        points.append(
            MacroDataPoint(
                indicator=event,
                date=obs_date,
                value=actual if actual is not None else 0.0,
                metadata=meta,
            )
        )

    points.sort(key=lambda p: p.date)
    return _filter_by_date(points, start_date, end_date)

"""央行 M2 月度货币供应量采集 (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.macro_china_money_supply()
# Expected columns: 统计时间, M2同比增速, M2, M1同比增速, M0同比增速
_DATE_COL = "统计时间"
_M2_YOY_COL = "M2同比增速"
_M2_ABS_COL = "M2"


def _akshare_fetch_m2() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_money_supply()
    return df[[_DATE_COL, _M2_YOY_COL, _M2_ABS_COL]].to_dict("records")


async def fetch_macro_m2(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch monthly M2 money supply from the PBoC via akshare.

    Returns one :class:`~oprim._macro_types.MacroDataPoint` per month with
    ``indicator="m2_yoy"`` (year-on-year growth %) and a second point with
    ``indicator="m2_abs"`` (total balance, 亿元).

    Args:
        start_date: Inclusive lower bound.  ``None`` = no lower bound.
        end_date:   Inclusive upper bound.  ``None`` = no upper bound.
        source:     Data source.  Only ``"akshare"`` is freely available;
                    ``"wind"`` and ``"tushare"`` require licensed access and
                    raise :exc:`MacroFetchError` immediately.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> from datetime import date
        >>> pts = await fetch_macro_m2(start_date=date(2024, 1, 1))
        >>> pts[0].indicator
        'm2_yoy'
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_m2)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_m2 failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(_DATE_COL)
        if raw_date is None:
            continue
        obs_date = date.fromisoformat(str(raw_date)[:10])
        meta = {"source": source, "unit_yoy": "%", "unit_abs": "亿元"}
        try:
            points.append(
                MacroDataPoint(
                    indicator="m2_yoy", date=obs_date, value=float(row[_M2_YOY_COL]), metadata=meta
                )
            )
        except (TypeError, ValueError):
            pass
        try:
            points.append(
                MacroDataPoint(
                    indicator="m2_abs", date=obs_date, value=float(row[_M2_ABS_COL]), metadata=meta
                )
            )
        except (TypeError, ValueError):
            pass

    points.sort(key=lambda p: p.date)
    return _filter_by_date(points, start_date, end_date)

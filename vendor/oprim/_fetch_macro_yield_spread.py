"""中美 10y 国债利差日度采集 (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.bond_zh_us_rate()
# Expected columns: 日期, 中国国债收益率10年, 美国国债收益率10年
_DATE_COL = "日期"
_CN_COL = "中国国债收益率10年"
_US_COL = "美国国债收益率10年"


def _akshare_fetch_yield_spread() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.bond_zh_us_rate()
    return df[[_DATE_COL, _CN_COL, _US_COL]].to_dict("records")


async def fetch_macro_yield_spread(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch daily China-US 10-year government bond yield spread via akshare.

    Returns one :class:`~oprim._macro_types.MacroDataPoint` per trading day with
    ``indicator="cn_us_yield_spread_10y"`` — value is (CN 10y yield − US 10y yield)
    in percentage points.  Individual CN and US yields are stored in ``metadata``.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_yield_spread(start_date=date(2024, 1, 1))
        >>> pts[0].indicator
        'cn_us_yield_spread_10y'
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_yield_spread)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_yield_spread failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(_DATE_COL)
        if raw_date is None:
            continue
        try:
            obs_date = date.fromisoformat(str(raw_date)[:10])
            cn = float(row[_CN_COL])
            us = float(row[_US_COL])
        except (TypeError, ValueError, KeyError):
            continue
        spread = round(cn - us, 4)
        points.append(
            MacroDataPoint(
                indicator="cn_us_yield_spread_10y",
                date=obs_date,
                value=spread,
                metadata={"source": source, "unit": "pp", "cn_10y": cn, "us_10y": us},
            )
        )

    points.sort(key=lambda p: p.date)
    return _filter_by_date(points, start_date, end_date)

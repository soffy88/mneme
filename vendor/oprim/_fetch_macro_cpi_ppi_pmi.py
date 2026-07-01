"""统计局 CPI / PPI / PMI 月度采集 (oprim B7).

Three indicators share the same NBS data source so they are fetched together.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare APIs:
#   ak.macro_china_cpi_monthly()    → columns: 日期, 全国-当月, 全国-同比增长, 全国-环比增长
#   ak.macro_china_ppi_monthly()    → columns: 日期, 当月, 同比增长, 环比增长
#   ak.macro_china_pmi_mfg_monthly()→ columns: 日期, 制造业-指数, 制造业-同比增长


def _akshare_fetch_cpi() -> list[dict[str, Any]]:
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_cpi_monthly()
    return df.to_dict("records")


def _akshare_fetch_ppi() -> list[dict[str, Any]]:
    import akshare as ak

    df = ak.macro_china_ppi_monthly()
    return df.to_dict("records")


def _akshare_fetch_pmi() -> list[dict[str, Any]]:
    import akshare as ak

    df = ak.macro_china_pmi_mfg_monthly()
    return df.to_dict("records")


def _rows_to_points(
    rows: list[dict[str, Any]],
    indicator: str,
    date_col: str,
    value_col: str,
    source: str,
    unit: str,
) -> list[MacroDataPoint]:
    pts: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(date_col)
        if raw_date is None:
            continue
        try:
            obs_date = date.fromisoformat(str(raw_date)[:10])
            val = float(row[value_col])
        except (TypeError, ValueError, KeyError):
            continue
        pts.append(
            MacroDataPoint(
                indicator=indicator,
                date=obs_date,
                value=val,
                metadata={"source": source, "unit": unit},
            )
        )
    return pts


async def fetch_macro_cpi_ppi_pmi(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch monthly CPI, PPI, and manufacturing PMI from NBS via akshare.

    Returns points with indicators ``"cpi_yoy"`` (%), ``"ppi_yoy"`` (%),
    and ``"pmi_mfg"`` (index value).  All three are fetched in parallel.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        Combined list of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_cpi_ppi_pmi(start_date=date(2024, 1, 1))
        >>> {p.indicator for p in pts} >= {"cpi_yoy", "ppi_yoy", "pmi_mfg"}
        True
    """
    _guard_source(source)
    try:
        cpi_rows, ppi_rows, pmi_rows = await asyncio.gather(
            asyncio.to_thread(_akshare_fetch_cpi),
            asyncio.to_thread(_akshare_fetch_ppi),
            asyncio.to_thread(_akshare_fetch_pmi),
        )
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_cpi_ppi_pmi failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    points += _rows_to_points(cpi_rows, "cpi_yoy", "日期", "全国-同比增长", source, "%")
    points += _rows_to_points(ppi_rows, "ppi_yoy", "日期", "同比增长", source, "%")
    points += _rows_to_points(pmi_rows, "pmi_mfg", "日期", "制造业-指数", source, "index")

    points.sort(key=lambda p: (p.date, p.indicator))
    return _filter_by_date(points, start_date, end_date)

"""PBoC 公开市场操作采集 — 逆回购 / MLF / SLF (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.macro_china_open_market_loan_rate()
# Expected columns: 日期, 类型, 操作量(亿元), 中标利率(%)
_DATE_COL = "日期"
_TYPE_COL = "类型"
_RATE_COL = "中标利率(%)"
_VOL_COL = "操作量(亿元)"

_TYPE_TO_INDICATOR = {
    "逆回购": "pboc_reverse_repo_rate",
    "MLF": "pboc_mlf_rate",
    "SLF": "pboc_slf_rate",
}


def _akshare_fetch_pboc() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_open_market_loan_rate()
    return df.to_dict("records")


async def fetch_macro_pboc(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch PBoC open market operations (reverse repo / MLF / SLF) via akshare.

    Indicator codes: ``"pboc_reverse_repo_rate"``, ``"pboc_mlf_rate"``,
    ``"pboc_slf_rate"``.  ``value`` is the winning bid rate (%).
    Volume (亿元) is placed in ``metadata["volume_bn"]``.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_pboc(start_date=date(2024, 1, 1))
        >>> pts[0].indicator in ("pboc_reverse_repo_rate", "pboc_mlf_rate", "pboc_slf_rate")
        True
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_pboc)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_pboc failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(_DATE_COL)
        op_type = str(row.get(_TYPE_COL, ""))
        indicator = _TYPE_TO_INDICATOR.get(op_type, f"pboc_{op_type}_rate")
        if raw_date is None:
            continue
        obs_date = date.fromisoformat(str(raw_date)[:10])
        try:
            rate = float(row[_RATE_COL])
        except (TypeError, ValueError, KeyError):
            continue
        meta: dict[str, Any] = {"source": source, "unit": "%", "op_type": op_type}
        try:
            meta["volume_bn"] = float(row[_VOL_COL])
        except (TypeError, ValueError, KeyError):
            pass
        points.append(MacroDataPoint(indicator=indicator, date=obs_date, value=rate, metadata=meta))

    points.sort(key=lambda p: p.date)
    return _filter_by_date(points, start_date, end_date)

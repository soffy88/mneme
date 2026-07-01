"""准备金率 (RRR) 不定期采集 (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.macro_china_reserve_ratio()
# Expected columns: 日期, 大型金融机构, 中小金融机构
_DATE_COL = "日期"
_LARGE_COL = "大型金融机构"
_SMALL_COL = "中小金融机构"


def _akshare_fetch_rrr() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_reserve_ratio()
    return df[[_DATE_COL, _LARGE_COL, _SMALL_COL]].to_dict("records")


async def fetch_macro_rrr(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch PBoC Reserve Requirement Ratio (RRR) changes via akshare.

    Returns two :class:`~oprim._macro_types.MacroDataPoint` per effective date:
    ``indicator="rrr_large"`` (大型金融机构 %) and ``indicator="rrr_small"``
    (中小金融机构 %).  Dates are irregular (only on change).

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_rrr(start_date=date(2023, 1, 1))
        >>> pts[0].indicator in ("rrr_large", "rrr_small")
        True
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_rrr)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_rrr failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    meta_base = {"source": source, "unit": "%"}
    for row in rows:
        raw_date = row.get(_DATE_COL)
        if raw_date is None:
            continue
        obs_date = date.fromisoformat(str(raw_date)[:10])
        for indicator, col in (("rrr_large", _LARGE_COL), ("rrr_small", _SMALL_COL)):
            try:
                points.append(
                    MacroDataPoint(
                        indicator=indicator,
                        date=obs_date,
                        value=float(row[col]),
                        metadata=meta_base,
                    )
                )
            except (TypeError, ValueError, KeyError):
                pass

    points.sort(key=lambda p: (p.date, p.indicator))
    return _filter_by_date(points, start_date, end_date)

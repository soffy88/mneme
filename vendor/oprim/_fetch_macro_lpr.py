"""LPR 1y / 5y 月度采集 (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.macro_china_lpr()
# Expected columns: 日期, 1年期LPR, 5年期以上LPR
_DATE_COL = "日期"
_LPR1Y_COL = "1年期LPR"
_LPR5Y_COL = "5年期以上LPR"


def _akshare_fetch_lpr() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.macro_china_lpr()
    return df[[_DATE_COL, _LPR1Y_COL, _LPR5Y_COL]].to_dict("records")


async def fetch_macro_lpr(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch monthly LPR (Loan Prime Rate) 1y and 5y+ from PBoC via akshare.

    Returns two :class:`~oprim._macro_types.MacroDataPoint` per adjustment date:
    ``indicator="lpr_1y"`` and ``indicator="lpr_5y"`` (both in %).
    LPR is only updated when changed, so dates are irregular.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_lpr(start_date=date(2024, 1, 1))
        >>> pts[0].indicator
        'lpr_1y'
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_lpr)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_lpr failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    meta_base = {"source": source, "unit": "%"}
    for row in rows:
        raw_date = row.get(_DATE_COL)
        if raw_date is None:
            continue
        obs_date = date.fromisoformat(str(raw_date)[:10])
        for indicator, col in (("lpr_1y", _LPR1Y_COL), ("lpr_5y", _LPR5Y_COL)):
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

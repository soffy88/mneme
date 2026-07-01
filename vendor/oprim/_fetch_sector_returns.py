"""板块涨幅查询 (oprim B8)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class SectorReturn(BaseModel):
    """单个板块涨幅条目.

    Attributes:
        sector_name: 板块名称.
        change_pct: 涨跌幅 (%).
        date: 交易日期.
        metadata: 成交额、换手率等扩展字段.
    """

    sector_name: str
    change_pct: float
    date: date
    metadata: dict[str, Any] = Field(default_factory=dict)


class SectorFetchError(OprimError):
    """Raised on fetch failure for fetch_sector_returns."""


# akshare API: ak.stock_board_industry_name_em()
# Expected columns: 板块名称, 涨跌幅, 日期
_NAME_COL = "板块名称"
_CHG_COL = "涨跌幅"
_DATE_COL = "日期"


def _akshare_fetch_sectors(as_of_date: date | None) -> list[dict[str, Any]]:
    """Sync akshare call — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.stock_board_industry_name_em()
    if _DATE_COL not in df.columns:
        df[_DATE_COL] = str(as_of_date or date.today())
    return df.to_dict("records")


async def fetch_sector_returns(
    *,
    as_of_date: date | None = None,
    top_n: int | None = None,
    source: Literal["akshare"] = "akshare",
) -> list[SectorReturn]:
    """Fetch Shenwan industry sector returns for a given date via akshare.

    Args:
        as_of_date: Target trading date.  ``None`` = most recent available.
        top_n:      If set, return only the top N sectors by ``change_pct``.
        source:     Currently only ``"akshare"`` is supported.

    Returns:
        List of :class:`SectorReturn` sorted by ``change_pct`` descending.

    Raises:
        SectorFetchError: On network error or unexpected response.

    Example:
        >>> sectors = await fetch_sector_returns(top_n=5)
        >>> len(sectors) <= 5
        True
    """
    if source != "akshare":
        raise SectorFetchError(f"source={source!r} not supported; use 'akshare'")
    try:
        rows = await asyncio.to_thread(_akshare_fetch_sectors, as_of_date)
    except SectorFetchError:
        raise
    except Exception as exc:
        raise SectorFetchError(f"fetch_sector_returns failed: {exc}") from exc

    obs_date = as_of_date or date.today()
    entries: list[SectorReturn] = []
    for row in rows:
        try:
            entries.append(
                SectorReturn(
                    sector_name=str(row.get(_NAME_COL, "")),
                    change_pct=float(row.get(_CHG_COL, 0.0)),
                    date=obs_date,
                    metadata={"source": source},
                )
            )
        except (TypeError, ValueError):
            continue

    entries.sort(key=lambda e: e.change_pct, reverse=True)
    return entries[:top_n] if top_n is not None else entries

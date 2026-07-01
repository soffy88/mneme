"""每日主题概念行情采集 (oprim B8)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class ThemeEntry(BaseModel):
    """单个主题概念条目.

    Attributes:
        theme_name: 概念名称.
        theme_code: 概念代码.
        change_pct: 当日涨幅 (%).
        date: 交易日期.
        metadata: 额外字段 (领涨股, 成分股数等).
    """

    theme_name: str
    theme_code: str = ""
    change_pct: float
    date: date
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThemesFetchError(OprimError):
    """Raised on fetch failure for fetch_themes_daily."""


# akshare API: ak.stock_board_concept_name_em()
# Expected columns: 板块名称, 板块代码, 涨跌幅, 日期 (or similar)
_NAME_COL = "板块名称"
_CODE_COL = "板块代码"
_CHG_COL = "涨跌幅"
_DATE_COL = "日期"


def _akshare_fetch_themes(as_of_date: date | None) -> list[dict[str, Any]]:
    """Sync akshare call — run via asyncio.to_thread."""
    import akshare as ak  # lazy import: pip install akshare

    df = ak.stock_board_concept_name_em()
    if _DATE_COL not in df.columns:
        df[_DATE_COL] = str(as_of_date or date.today())
    return df.to_dict("records")


async def fetch_themes_daily(
    *,
    as_of_date: date | None = None,
    source: Literal["akshare"] = "akshare",
) -> list[ThemeEntry]:
    """Fetch daily concept-theme rankings from East Money via akshare.

    Args:
        as_of_date: Target date.  ``None`` = today (akshare returns most recent).
        source:     Currently only ``"akshare"`` is supported.

    Returns:
        List of :class:`ThemeEntry` sorted by ``change_pct`` descending.

    Raises:
        ThemesFetchError: On network error or unexpected response.

    Example:
        >>> themes = await fetch_themes_daily(as_of_date=date(2024, 3, 1))
        >>> themes[0].theme_name
        '人工智能'
    """
    if source != "akshare":
        raise ThemesFetchError(f"source={source!r} not supported; use 'akshare'")
    try:
        rows = await asyncio.to_thread(_akshare_fetch_themes, as_of_date)
    except ThemesFetchError:
        raise
    except Exception as exc:
        raise ThemesFetchError(f"fetch_themes_daily failed: {exc}") from exc

    obs_date = as_of_date or date.today()
    entries: list[ThemeEntry] = []
    for row in rows:
        try:
            entries.append(
                ThemeEntry(
                    theme_name=str(row.get(_NAME_COL, "")),
                    theme_code=str(row.get(_CODE_COL, "")),
                    change_pct=float(row.get(_CHG_COL, 0.0)),
                    date=obs_date,
                    metadata={"source": source},
                )
            )
        except (TypeError, ValueError):
            continue

    entries.sort(key=lambda e: e.change_pct, reverse=True)
    return entries

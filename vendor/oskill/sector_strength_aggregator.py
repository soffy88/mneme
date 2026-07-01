"""板块强度聚合 — 主题概念 → 申万行业 → 百分位排名 (oskill B10)."""

from __future__ import annotations

from datetime import date
from typing import Literal

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel

from oskill._exceptions import OskillError


class SectorStrengthRow(BaseModel):
    """单个申万行业的板块强度结果.

    Attributes:
        sw_industry:    申万行业名称.
        avg_change_pct: 该行业下各概念涨跌幅均值.
        theme_count:    覆盖的概念主题数.
        strength_pct:   跨行业百分位强度排名.
    """

    sw_industry: str
    avg_change_pct: float
    theme_count: int
    strength_pct: float


class SectorStrengthReport(BaseModel):
    """sector_strength_aggregator 结果."""

    rows: list[SectorStrengthRow]
    as_of_date: date | None
    total_themes: int


async def sector_strength_aggregator(
    *,
    mapping_table: dict[str, str],
    as_of_date: date | None = None,
    top_n: int | None = None,
    source: Literal["akshare"] = "akshare",
) -> SectorStrengthReport:
    """Aggregate daily theme performance into SW industry strength scores.

    Internal oprim composition:
    - oprim.fetch_themes_daily          (async; fetches daily concept returns)
    - oprim.theme_to_sw_industry_mapping (sync; maps themes to SW industries)
    - oprim.percentile_rank              (cross-sectional ranking of industry strengths)

    Args:
        mapping_table:  ``{theme_name: sw_industry}`` injected by caller.
        as_of_date:     Target date; ``None`` = most recent.
        top_n:          Return only top N industries by strength.
        source:         Data source.

    Returns:
        :class:`SectorStrengthReport` sorted by strength descending.

    Raises:
        OskillError: On theme fetch failure.

    Example:
        >>> table = {"人工智能": "电子", "新能源汽车": "汽车"}
        >>> r = await sector_strength_aggregator(mapping_table=table)
        >>> r.total_themes >= 0
        True
    """
    try:
        themes = await oprim.fetch_themes_daily(as_of_date=as_of_date, source=source)
    except Exception as exc:
        raise OskillError(f"sector_strength_aggregator: theme fetch failed: {exc}") from exc

    if not themes:
        return SectorStrengthReport(rows=[], as_of_date=as_of_date, total_themes=0)

    theme_names = [t.theme_name for t in themes]
    mappings = oprim.theme_to_sw_industry_mapping(
        theme_names=theme_names, mapping_table=mapping_table
    )

    industry_changes: dict[str, list[float]] = {}
    for theme, mapping in zip(themes, mappings):
        if mapping.matched and mapping.sw_industry:
            industry_changes.setdefault(mapping.sw_industry, []).append(theme.change_pct)

    if not industry_changes:
        return SectorStrengthReport(rows=[], as_of_date=as_of_date, total_themes=len(themes))

    avg_changes = {ind: sum(chgs) / len(chgs) for ind, chgs in industry_changes.items()}
    industries = list(avg_changes.keys())
    avgs = list(avg_changes.values())

    if len(avgs) >= 2:
        strength_pcts = oprim.percentile_rank(pd.DataFrame({"v": avgs}), method="cross_sectional")[
            "v"
        ].tolist()
    else:
        strength_pcts = [50.0] * len(avgs)

    rows = [
        SectorStrengthRow(
            sw_industry=industries[i],
            avg_change_pct=round(avgs[i], 4),
            theme_count=len(industry_changes[industries[i]]),
            strength_pct=round(float(strength_pcts[i]), 4),
        )
        for i in range(len(industries))
    ]
    rows.sort(key=lambda r: r.strength_pct, reverse=True)
    if top_n is not None:
        rows = rows[:top_n]

    return SectorStrengthReport(rows=rows, as_of_date=as_of_date, total_themes=len(themes))

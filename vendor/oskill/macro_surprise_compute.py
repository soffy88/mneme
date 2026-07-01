"""宏观数据惊喜分数计算 (oskill B10)."""

from __future__ import annotations

from datetime import date
from typing import Literal

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel

from oskill._exceptions import OskillError


class MacroSurpriseItem(BaseModel):
    """单条宏观惊喜结果.

    Attributes:
        indicator: 事件名称.
        date:      发布日期.
        actual:    实际值.
        forecast:  预期值 (None 时无法计算惊喜).
        surprise_raw: actual - forecast.
        surprise_z:   跨时序 z-score (None 若样本不足).
        surprise_pct: 全集百分位 (None 若样本不足).
    """

    indicator: str
    date: date
    actual: float
    forecast: float | None
    surprise_raw: float | None
    surprise_z: float | None = None
    surprise_pct: float | None = None


class MacroSurpriseReport(BaseModel):
    """macro_surprise_compute 结果.

    Attributes:
        items:       各事件惊喜得分列表,按日期升序.
        shock_count: |z| > 1.5 的高惊喜事件数.
    """

    items: list[MacroSurpriseItem]
    shock_count: int


async def macro_surprise_compute(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["akshare"] = "akshare",
    zscore_min_periods: int = 6,
) -> MacroSurpriseReport:
    """Compute macro data surprise scores from economic calendar actual vs forecast.

    Internal oprim composition:
    - oprim.fetch_macro_calendar  (async; fetches actual + forecast values)
    - oprim.zscore_normalize      (normalises raw surprise series cross-sectionally)
    - oprim.percentile_rank       (computes historical percentile of each surprise)

    Args:
        start_date:         Inclusive lower bound for calendar events.
        end_date:           Inclusive upper bound.
        source:             Data source — currently only ``"akshare"``.
        zscore_min_periods: Minimum number of non-null surprises required before
                            computing z-score / percentile (default 6).

    Returns:
        :class:`MacroSurpriseReport` with surprise scores and shock count.

    Raises:
        OskillError: On fetch failure or unexpected data shape.

    Example:
        >>> from datetime import date
        >>> report = await macro_surprise_compute(start_date=date(2024, 1, 1))
        >>> report.shock_count >= 0
        True
    """
    try:
        points = await oprim.fetch_macro_calendar(
            start_date=start_date, end_date=end_date, source=source
        )
    except Exception as exc:
        raise OskillError(f"macro_surprise_compute: calendar fetch failed: {exc}") from exc

    items: list[MacroSurpriseItem] = []
    for pt in points:
        forecast = pt.metadata.get("forecast")
        actual = pt.value
        surprise_raw = (actual - float(forecast)) if forecast is not None else None
        items.append(
            MacroSurpriseItem(
                indicator=pt.indicator,
                date=pt.date,
                actual=actual,
                forecast=float(forecast) if forecast is not None else None,
                surprise_raw=surprise_raw,
            )
        )

    raw_vals = [i.surprise_raw for i in items if i.surprise_raw is not None]
    if len(raw_vals) >= zscore_min_periods:
        sr = pd.Series(raw_vals, dtype=float)
        z_vals = oprim.zscore_normalize(sr, window=None, min_periods=1).fillna(0.0).tolist()
        pct_vals = oprim.percentile_rank(pd.DataFrame({"v": raw_vals}), method="cross_sectional")[
            "v"
        ].tolist()
        j = 0
        for item in items:
            if item.surprise_raw is not None:
                item.surprise_z = float(z_vals[j])
                item.surprise_pct = float(pct_vals[j])
                j += 1

    shock_count = sum(1 for i in items if i.surprise_z is not None and abs(i.surprise_z) > 1.5)
    return MacroSurpriseReport(items=sorted(items, key=lambda x: x.date), shock_count=shock_count)

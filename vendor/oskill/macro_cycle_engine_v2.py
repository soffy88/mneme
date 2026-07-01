"""宏观周期引擎 v2 — M2 + LPR + PBOC 联合规则分类 (oskill B10)."""

from __future__ import annotations

import asyncio
from typing import Literal, cast

import oprim
from oprim._macro_types import MacroDataPoint
from pydantic import BaseModel, Field

from oskill._exceptions import OskillError

_PHASES = Literal["monetary_easing", "monetary_tightening", "expansion", "contraction", "uncertain"]


class MacroCycleResult(BaseModel):
    """macro_cycle_engine_v2 结果.

    Attributes:
        phase:      当前宏观周期阶段.
        confidence: 置信度 0.0–1.0 (命中规则数 / 全部规则数).
        evidence:   各指标末值字典.
    """

    phase: _PHASES
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, object]


async def macro_cycle_engine_v2(
    *,
    lookback_months: int = 12,
    source: Literal["akshare"] = "akshare",
) -> MacroCycleResult:
    """Classify the current macro cycle phase using three PBoC data streams.

    Internal oprim composition:
    - oprim.fetch_macro_m2    (async; monthly M2 YoY)
    - oprim.fetch_macro_lpr   (async; LPR 1y / 5y+)
    - oprim.fetch_macro_pboc  (async; open market operations rate)

    Rules (majority-vote on last available values):
    - m2_trend rising + lpr_trend falling + pboc_rate falling → monetary_easing
    - m2_trend falling + lpr_trend rising + pboc_rate rising  → monetary_tightening
    - m2_trend rising + lpr_trend stable                      → expansion
    - m2_trend falling + lpr_trend stable                     → contraction
    - otherwise                                               → uncertain

    Args:
        lookback_months: Number of months to inspect for trend direction.
        source:          Data source.

    Returns:
        :class:`MacroCycleResult`.

    Raises:
        OskillError: On fetch failure or insufficient data.

    Example:
        >>> r = await macro_cycle_engine_v2(lookback_months=6)
        >>> r.phase in (
        ...     "monetary_easing","monetary_tightening","expansion","contraction","uncertain"
        ... )
        True
    """
    try:
        m2_pts, lpr_pts, pboc_pts = await asyncio.gather(
            oprim.fetch_macro_m2(source=source),
            oprim.fetch_macro_lpr(source=source),
            oprim.fetch_macro_pboc(source=source),
        )
    except Exception as exc:
        raise OskillError(f"macro_cycle_engine_v2: fetch failed: {exc}") from exc

    def _last_n(pts: list[MacroDataPoint], indicator: str, n: int = 2) -> list[float]:
        filtered = [p for p in pts if p.indicator == indicator]
        filtered.sort(key=lambda p: p.date)
        return [p.value for p in filtered[-n:]]

    def _trend(vals: list[float]) -> str:
        if len(vals) < 2:
            return "stable"
        return "rising" if vals[-1] > vals[-2] else ("falling" if vals[-1] < vals[-2] else "stable")

    m2_vals = _last_n(m2_pts, "m2_yoy", lookback_months)
    lpr1_vals = _last_n(lpr_pts, "lpr_1y", lookback_months)
    pboc_vals = _last_n(pboc_pts, "pboc_mlf_rate", lookback_months) or _last_n(
        pboc_pts, "pboc_reverse_repo_rate", lookback_months
    )

    m2_trend = _trend(m2_vals)
    lpr_trend = _trend(lpr1_vals)
    pboc_trend = _trend(pboc_vals)

    easing_hits = sum([m2_trend == "rising", lpr_trend == "falling", pboc_trend == "falling"])
    tight_hits = sum([m2_trend == "falling", lpr_trend == "rising", pboc_trend == "rising"])

    phase_str: str
    if easing_hits >= 2:
        phase_str, conf = "monetary_easing", easing_hits / 3
    elif tight_hits >= 2:
        phase_str, conf = "monetary_tightening", tight_hits / 3
    elif m2_trend == "rising":
        phase_str, conf = "expansion", 0.5
    elif m2_trend == "falling":
        phase_str, conf = "contraction", 0.5
    else:
        phase_str, conf = "uncertain", 0.3

    return MacroCycleResult(
        phase=cast(_PHASES, phase_str),
        confidence=round(conf, 4),
        evidence={
            "m2_trend": m2_trend,
            "lpr_trend": lpr_trend,
            "pboc_trend": pboc_trend,
            "m2_last": m2_vals[-1] if m2_vals else None,
            "lpr1_last": lpr1_vals[-1] if lpr1_vals else None,
        },
    )

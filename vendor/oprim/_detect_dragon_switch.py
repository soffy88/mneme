"""龙头切换检测 — 原 Top1 滞涨 + 新 Top3 量比放大 (oprim B9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError


class DragonSwitchConfig(BaseModel):
    """龙头切换检测阈值配置.

    Attributes:
        top1_underperform_threshold: 原龙头涨幅上限 (如 0.0 表示不涨即算滞涨).
        new_top3_vol_ratio_threshold: 新候补龙头量比下限 (如 2.0 表示需达到 2 倍均量).
        min_new_leaders_above_threshold: 新 Top3 中需满足量比的最少个数.
    """

    top1_underperform_threshold: float = Field(default=0.0)
    new_top3_vol_ratio_threshold: float = Field(default=2.0, gt=0)
    min_new_leaders_above_threshold: int = Field(default=2, ge=1)


def detect_dragon_switch(
    *,
    top1_change_pct: float,
    new_top3_vol_ratios: list[float],
    config: DragonSwitchConfig = DragonSwitchConfig(),
) -> DetectorSignal | None:
    """Detect a sector leadership rotation (龙头切换).

    Triggers when:
    - Original leader's return < ``config.top1_underperform_threshold``
    - At least ``config.min_new_leaders_above_threshold`` of the new candidates
      have ``volume_ratio > config.new_top3_vol_ratio_threshold``

    Args:
        top1_change_pct:     Original sector leader's current % change (e.g. -0.02 = -2 %).
        new_top3_vol_ratios: Volume ratios of the top-3 new candidates (must have ≥ 1 element).
        config:              Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If ``new_top3_vol_ratios`` is empty.

    Example:
        >>> sig = detect_dragon_switch(
        ...     top1_change_pct=-0.02,
        ...     new_top3_vol_ratios=[3.1, 2.8, 1.5],
        ... )
        >>> sig is not None
        True
    """
    if not new_top3_vol_ratios:
        raise OprimError("new_top3_vol_ratios must not be empty")

    if top1_change_pct >= config.top1_underperform_threshold:
        return None

    above = [r for r in new_top3_vol_ratios if r > config.new_top3_vol_ratio_threshold]
    if len(above) < config.min_new_leaders_above_threshold:
        return None

    avg_new_vol = sum(above) / len(above)
    severity = "high" if avg_new_vol > config.new_top3_vol_ratio_threshold * 2 else "medium"

    return DetectorSignal(
        detector_name="dragon_switch",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "top1_change_pct": round(top1_change_pct, 6),
            "new_top3_vol_ratios": new_top3_vol_ratios,
            "leaders_above_threshold": len(above),
            "avg_new_vol_ratio": round(avg_new_vol, 4),
        },
    )

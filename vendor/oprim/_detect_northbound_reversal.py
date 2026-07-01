"""北向资金逆转检测 — 连续净流入后突然净流出 (oprim B9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError


class NorthboundReversalConfig(BaseModel):
    """北向逆转检测阈值配置.

    Attributes:
        min_inflow_streak_mins: 逆转前需要的连续净流入分钟数.
        reversal_threshold:     逆转时净流出量下限 (亿元, 负数, 如 -2.0 表示净流出 2 亿).
    """

    min_inflow_streak_mins: int = Field(default=5, ge=1)
    reversal_threshold: float = Field(default=-2.0, le=0)


def detect_northbound_reversal(
    *,
    flow_series: list[float],
    config: NorthboundReversalConfig = NorthboundReversalConfig(),
) -> DetectorSignal | None:
    """Detect a sudden reversal of northbound (沪深股通) capital flow.

    Triggers when:
    - The last bar shows significant net outflow ≤ ``config.reversal_threshold``
    - The preceding bars form a consecutive inflow streak ≥ ``config.min_inflow_streak_mins``

    Args:
        flow_series: Per-minute northbound net flow in 亿元 (positive = inflow).
                     Must have ≥ ``config.min_inflow_streak_mins + 1`` elements.
        config:      Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If ``flow_series`` has fewer than 2 elements.

    Example:
        >>> flows = [1.0, 1.5, 2.0, 0.8, 1.2, -3.5]  # inflow streak then reversal
        >>> sig = detect_northbound_reversal(
        ...     flow_series=flows,
        ...     config=NorthboundReversalConfig(min_inflow_streak_mins=3, reversal_threshold=-2.0),
        ... )
        >>> sig is not None
        True
    """
    if len(flow_series) < 2:
        raise OprimError(f"flow_series must have ≥ 2 elements, got {len(flow_series)}")

    last_flow = flow_series[-1]
    if last_flow > config.reversal_threshold:
        return None

    streak = 0
    for f in reversed(flow_series[:-1]):
        if f > 0:
            streak += 1
        else:
            break

    if streak < config.min_inflow_streak_mins:
        return None

    severity = "critical" if last_flow <= config.reversal_threshold * 2 else "high"

    return DetectorSignal(
        detector_name="northbound_reversal",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "last_flow_bn": last_flow,
            "inflow_streak_mins": streak,
            "reversal_threshold": config.reversal_threshold,
            "cumulative_inflow_bn": round(sum(f for f in flow_series[-(streak + 1) : -1]), 4),
        },
    )

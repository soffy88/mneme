"""异常放量检测 — 量比超阈值 + 价格 MA20 上方 + 5min 涨幅 (oprim B9).

内部调用既有 oprim.volume_ratio (符合 oprim 单一调用约定).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError
from oprim.volume_ratio import volume_ratio


class VolumeSpikeConfig(BaseModel):
    """异常放量检测阈值配置.

    Attributes:
        vol_ratio_threshold:     量比触发下限.
        ma_period:               均线周期 (如 20 表示 MA20).
        five_min_return_threshold: 5min 涨幅触发下限 (如 0.01 表示 1%).
    """

    vol_ratio_threshold: float = Field(default=3.0, gt=0)
    ma_period: int = Field(default=20, ge=2)
    five_min_return_threshold: float = Field(default=0.01, ge=0)


def detect_volume_spike(
    *,
    close: list[float],
    volumes: list[float],
    five_min_return: float,
    config: VolumeSpikeConfig = VolumeSpikeConfig(),
) -> DetectorSignal | None:
    """Detect an abnormal volume spike with price confirmation.

    Triggers when ALL three conditions are met:
    - ``volume_ratio(volumes) > config.vol_ratio_threshold``
    - ``close[-1] > MA(close, config.ma_period)``
    - ``five_min_return > config.five_min_return_threshold``

    Uses :func:`oprim.volume_ratio` for the volume-ratio computation.

    Args:
        close:            Daily closing price series (oldest first, ≥ ``ma_period`` bars).
        volumes:          Daily volume series, same length as ``close``.
        five_min_return:  Latest 5-minute price return (e.g. 0.015 = +1.5 %).
        config:           Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If series lengths differ.

    Example:
        >>> close = [10.0] * 20 + [10.5]
        >>> volumes = [1000.0] * 20 + [5000.0]
        >>> sig = detect_volume_spike(close=close, volumes=volumes, five_min_return=0.015)
        >>> sig is not None
        True
    """
    if len(close) != len(volumes):
        raise OprimError(
            f"close and volumes must have equal length, got {len(close)} vs {len(volumes)}"
        )
    if len(close) < 2:
        raise OprimError(f"Need ≥ 2 price bars, got {len(close)}")

    vr = volume_ratio(volumes=volumes, window=5)
    if vr <= config.vol_ratio_threshold:
        return None

    period = min(config.ma_period, len(close))
    ma = float(np.mean(close[-period:]))
    if close[-1] <= ma:
        return None

    if five_min_return <= config.five_min_return_threshold:
        return None

    severity = "high" if vr >= config.vol_ratio_threshold * 2 else "medium"

    return DetectorSignal(
        detector_name="volume_spike",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "volume_ratio": round(vr, 4),
            "ma_period": period,
            "ma_value": round(ma, 4),
            "current_close": close[-1],
            "five_min_return": round(five_min_return, 6),
        },
    )

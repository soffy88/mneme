"""涨停炸板检测 — 涨停 → 打开 + 放量 (oprim B9).

内部调用既有 oprim.limit_status_calc (符合 oprim 单一调用约定).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError
from oprim.limit_status_calc import limit_status_calc


class LimitBoardExplosionConfig(BaseModel):
    """涨停炸板检测阈值配置.

    Attributes:
        limit_pct:      涨停比例 (如 0.10 表示 10%).
        vol_multiplier: 炸板时成交量需达到前 N 根均量的倍数.
        vol_avg_window: 计算均量的窗口长度 (根).
    """

    limit_pct: float = Field(default=0.10, gt=0)
    vol_multiplier: float = Field(default=2.0, gt=0)
    vol_avg_window: int = Field(default=5, ge=1)


def detect_limit_board_explosion(
    *,
    close: list[float],
    volumes: list[float],
    config: LimitBoardExplosionConfig = LimitBoardExplosionConfig(),
) -> DetectorSignal | None:
    """Detect a 涨停炸板 (limit-up broken) event with volume surge.

    Triggers when:
    - The second-to-last bar was at ``"limit_up"`` status
    - The last bar is ``"normal"`` (board broken)
    - Volume on the break bar ≥ ``config.vol_multiplier × avg_volume``

    Uses :func:`oprim.limit_status_calc` internally to classify statuses.
    Close and volume series must be in chronological order (oldest first).

    Args:
        close:   Price series (≥ ``config.vol_avg_window + 3`` elements recommended).
        volumes: Volume series, same length as ``close``.
        config:  Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If series lengths differ or too short.

    Example:
        >>> # Stock at limit_up yesterday, broken today with 3× volume
        >>> close = [10.0, 11.0, 10.5]   # limit_up → normal
        >>> volumes = [1000.0, 2000.0, 6000.0]
        >>> sig = detect_limit_board_explosion(close=close, volumes=volumes,
        ...     config=LimitBoardExplosionConfig(limit_pct=0.10, vol_multiplier=2.0))
    """
    n = len(close)
    if len(volumes) != n:
        raise OprimError(f"close and volumes must have equal length, got {n} vs {len(volumes)}")
    if n < 3:
        raise OprimError(f"Need ≥ 3 price bars, got {n}")

    statuses = limit_status_calc(close=close, limit_pct=config.limit_pct, lookback=2).recent
    if len(statuses) < 2:
        return None

    prev_status, curr_status = statuses[-2], statuses[-1]
    if prev_status != "limit_up" or curr_status != "normal":
        return None

    window = min(config.vol_avg_window, n - 1)
    avg_vol = float(np.mean(volumes[-(window + 1) : -1])) if window > 0 else float(volumes[-2])
    curr_vol = volumes[-1]

    if avg_vol <= 0 or curr_vol < config.vol_multiplier * avg_vol:
        return None

    vol_ratio = round(curr_vol / avg_vol, 4) if avg_vol > 0 else 0.0
    severity = "critical" if vol_ratio >= config.vol_multiplier * 2 else "high"

    return DetectorSignal(
        detector_name="limit_board_explosion",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "prev_status": prev_status,
            "curr_status": curr_status,
            "break_volume": curr_vol,
            "avg_volume": round(avg_vol, 2),
            "vol_ratio": vol_ratio,
        },
    )

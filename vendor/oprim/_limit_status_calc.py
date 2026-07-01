"""A股涨跌停状态判定 (oprim)."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class LimitStatusResult(BaseModel):
    """涨跌停状态结果."""
    recent: list[str] = Field(..., description="近 lookback 日状态 ['limit_up'|'limit_down'|'normal']")


def limit_status_calc(
    *,
    close: list[float],
    limit_pct: float = 0.10,
    lookback: int = 5,
) -> LimitStatusResult:
    """A股涨跌停状态判定. 按相邻日涨跌幅 vs limit_pct 标记.

    Args:
        close: 价格序列, 时间正序.
        limit_pct: 涨跌停比例 (如 0.10).
        lookback: 返回最近的交易日数.

    Returns:
        LimitStatusResult(recent=[...]).
    """
    T = len(close)
    if T < 2:
        # If only 1 day, cannot determine status relative to previous.
        # But if lookback is requested, we might need at least lookback + 1.
        if lookback > 0:
             raise OprimError(f"Sequence length {T} insufficient to determine status for lookback {lookback}")
        return LimitStatusResult(recent=[])

    if lookback > T - 1:
        raise OprimError(f"lookback {lookback} exceeds available status points {T-1}")

    c = np.asarray(close, dtype=np.float64)
    # Calculate daily returns (pct change)
    # Status for day t is based on c[t] / c[t-1] - 1
    # We use a small epsilon for float comparison
    eps = 1e-6
    
    statuses = []
    # We only need to compute for the last 'lookback' transitions
    start_idx = T - lookback
    for t in range(start_idx, T):
        prev_c = c[t-1]
        curr_c = c[t]
        ret = curr_c / prev_c - 1.0
        
        if ret >= limit_pct - eps:
            statuses.append("limit_up")
        elif ret <= -limit_pct + eps:
            statuses.append("limit_down")
        else:
            statuses.append("normal")
            
    return LimitStatusResult(recent=statuses)

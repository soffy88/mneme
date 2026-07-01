"""KDJ 随机指标 — A股技术指标 (oprim)."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class KDJResult(BaseModel):
    """KDJ 结果集."""
    k: list[float] = Field(..., description="K 序列")
    d: list[float] = Field(..., description="D 序列")
    j: list[float] = Field(..., description="J 序列")


def kdj(
    *,
    high: list[float],
    low: list[float],
    close: list[float],
    n: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> KDJResult:
    """KDJ 随机指标. 输入 OHLC 序列(时间正序), 输出 K/D/J 三序列.

    Args:
        high/low/close: 价格序列, 等长, 时间正序.
        n: RSV 周期, 默认 9.
        k_smooth/d_smooth: K/D 平滑周期, 默认 3.

    Returns:
        KDJResult(k=[...], d=[...], j=[...]).

    Raises:
        OprimError: 序列长度不等或 < n.

    Example:
        >>> kdj(high=[10, 11, 12], low=[9, 10, 11], close=[10.5, 11.5, 12.5], n=2)
    """
    T = len(close)
    if len(high) != T or len(low) != T:
        raise OprimError(f"Length mismatch: high({len(high)}), low({len(low)}), close({T})")
    if T < n:
        raise OprimError(f"Sequence length {T} is less than period n={n}")
    if n < 1:
        raise OprimError(f"n must be >= 1, got {n}")
    if k_smooth < 1 or d_smooth < 1:
        raise OprimError(f"smooth periods must be >= 1, got k_smooth={k_smooth}, d_smooth={d_smooth}")

    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)

    alpha_k = 1.0 / k_smooth
    alpha_d = 1.0 / d_smooth

    k_arr = np.empty(T, dtype=np.float64)
    d_arr = np.empty(T, dtype=np.float64)
    
    k_prev = 50.0
    d_prev = 50.0

    for t in range(T):
        start = max(0, t - n + 1)
        # For the first n-1 elements, we follow standard practice or cumulative min/max
        # But SPEC says T < n raises OprimError, implying we need at least n data points.
        lo_n = l[start : t + 1].min()
        hi_n = h[start : t + 1].max()
        rng = hi_n - lo_n
        
        # RSV (Raw Stochastic Value)
        rsv = 50.0 if rng < 1e-12 else (c[t] - lo_n) / rng * 100.0
        
        k_t = (1 - alpha_k) * k_prev + alpha_k * rsv
        d_t = (1 - alpha_d) * d_prev + alpha_d * k_t
        
        k_arr[t] = k_t
        d_arr[t] = d_t
        k_prev = k_t
        d_prev = d_t

    j_arr = 3.0 * k_arr - 2.0 * d_arr
    
    return KDJResult(
        k=k_arr.tolist(),
        d=d_arr.tolist(),
        j=j_arr.tolist()
    )

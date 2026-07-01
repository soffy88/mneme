"""量比计算 (oprim)."""

from __future__ import annotations

import numpy as np
from oprim._exceptions import OprimError


def volume_ratio(
    *, 
    volumes: list[float], 
    window: int = 5
) -> float:
    """量比 = 最新量 / 前 window 日均量. 数据不足返回 1.0.

    Args:
        volumes: 成交量序列, 时间正序.
        window: 均量周期.

    Returns:
        量比数值.
    """
    if len(volumes) < window + 1:
        return 1.0
    
    v = np.asarray(volumes, dtype=np.float64)
    latest_v = v[-1]
    avg_v = np.mean(v[-(window+1):-1])
    
    if abs(avg_v) < 1e-12:
        return 1.0
        
    return float(latest_v / avg_v)

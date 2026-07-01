"""K线形态识别 (oprim)."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class OHLCVInput(BaseModel):
    """OHLCV 数据输入."""
    open: list[float] = Field(..., description="开盘价")
    high: list[float] = Field(..., description="最高价")
    low: list[float] = Field(..., description="最低价")
    close: list[float] = Field(..., description="收盘价")
    volume: list[float] = Field(..., description="成交量")


class PatternMatch(BaseModel):
    """识别到的形态."""
    name: str = Field(..., description="形态名称")
    bullish_score: float = Field(0.0, description="看多得分 [0, 1]")
    bearish_score: float = Field(0.0, description="看空得分 [0, 1]")
    start_idx: int = Field(..., description="起始索引")
    end_idx: int = Field(..., description="结束索引")


def pattern_detection(
    *, 
    ohlcv: OHLCVInput
) -> list[PatternMatch]:
    """K线技术形态识别(纯数值算法).

    Args:
        ohlcv: 价格与成交量序列.

    Returns:
        PatternMatch 列表.
    """
    T = len(ohlcv.close)
    if T < 1:
        return []

    o = np.asarray(ohlcv.open)
    h = np.asarray(ohlcv.high)
    l = np.asarray(ohlcv.low)
    c = np.asarray(ohlcv.close)
    
    results: list[PatternMatch] = []
    
    # 示例: 锤子线 (Hammer)
    # 下影线是实体的 2 倍以上, 上影线很短
    for i in range(T):
        body = abs(c[i] - o[i])
        lower_shadow = min(o[i], c[i]) - l[i]
        upper_shadow = h[i] - max(o[i], c[i])
        
        if body > 0 and lower_shadow > 2 * body and upper_shadow < 0.2 * body:
            results.append(PatternMatch(
                name="hammer",
                bullish_score=0.8,
                bearish_score=0.0,
                start_idx=i,
                end_idx=i
            ))
            
    # 示例: 吞没形态 (Engulfing)
    if T >= 2:
        for i in range(1, T):
            # 看多吞没: 前一根阴线, 后一根阳线且包住前一根实体
            if c[i-1] < o[i-1] and c[i] > o[i]:
                if o[i] <= c[i-1] and c[i] >= o[i-1]:
                    results.append(PatternMatch(
                        name="bullish_engulfing",
                        bullish_score=0.9,
                        bearish_score=0.0,
                        start_idx=i-1,
                        end_idx=i
                    ))
            # 看空吞没
            elif c[i-1] > o[i-1] and c[i] < o[i]:
                if o[i] >= c[i-1] and c[i] <= o[i-1]:
                    results.append(PatternMatch(
                        name="bearish_engulfing",
                        bullish_score=0.0,
                        bearish_score=0.9,
                        start_idx=i-1,
                        end_idx=i
                    ))
                
    return results

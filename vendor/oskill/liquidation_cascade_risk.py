"""清算级联风险评估."""

from typing import Literal

import pandas as pd
from oprim.time_series import percentile_rank
from pydantic import BaseModel, Field


class LiquidationCascadeInput(BaseModel):
    """清算级联风险输入."""

    symbol: str
    oi_history: list[float] = Field(..., description="OI 历史序列 (用于算分位), 最近在后")
    current_oi: float
    funding_rate: float = Field(..., description="当前资金费率 (8h, 如 0.0001 = 0.01%)")
    funding_history: list[float] = Field(..., description="funding 历史序列")
    crowding_score: float = Field(
        ..., ge=0.0, le=1.0, description="拥挤度 0-1, 来自 compute_signal_crowding"
    )
    perp_basis: float = Field(..., description="永续基差 (perp - spot) / spot")
    cross_exchange_funding_diff: float = Field(0.0, description="跨所 funding 背离")


class LiquidationCascadeResult(BaseModel):
    """清算级联风险结果."""

    symbol: str
    risk_level: Literal["low", "elevated", "high", "extreme"]
    direction_bias: Literal["long_squeeze", "short_squeeze", "neutral"]
    risk_score: float = Field(..., ge=0.0, le=1.0, description="综合风险分 0-1")
    components: dict[str, float] = Field(
        ..., description="各分量贡献 (oi_percentile/funding_extremity/crowding/basis)"
    )
    rationale: str = Field(..., description="判断依据简述")


def _pct_rank_scalar(series: list[float], value: float) -> float:
    """计算 value 在 series 中的分位 (0-1), 使用 oprim.percentile_rank."""
    s = pd.Series(series + [value])
    ranks = percentile_rank(s, method="expanding")
    result: float = float(ranks.iloc[-1])  # type: ignore[arg-type]
    return result


def liquidation_cascade_risk(
    *,
    data: LiquidationCascadeInput,
    oi_percentile_threshold: float = 0.85,
    funding_extreme_threshold: float = 0.0005,
    crowding_threshold: float = 0.7,
) -> LiquidationCascadeResult:
    """评估清算级联风险.

    组合 OI 历史分位 + funding 极端度 + 拥挤方向 + 基差背离 → risk_level + direction_bias。

    Args:
        data: 清算风险输入 (OI/funding/拥挤度/基差).
        oi_percentile_threshold: OI 分位告警阈值, 默认 0.85 (85 分位).
        funding_extreme_threshold: funding 极端阈值, 默认 0.0005 (0.05%/8h).
        crowding_threshold: 拥挤度告警阈值, 默认 0.7.

    Returns:
        LiquidationCascadeResult: 风险等级 + 方向偏置 + 分量贡献.

    Raises:
        ValueError: oi_history/funding_history 为空, 或 current_oi <= 0.

    Example:
        >>> data = LiquidationCascadeInput(
        ...     symbol="BTCUSDT", oi_history=[1e9, 1.1e9, 1.05e9], current_oi=1.2e9,
        ...     funding_rate=0.0008, funding_history=[0.0001, 0.0002, 0.0003],
        ...     crowding_score=0.82, perp_basis=0.003,
        ... )
        >>> result = liquidation_cascade_risk(data=data)
        >>> result.direction_bias
        'long_squeeze'
    """
    if not data.oi_history:
        raise ValueError("oi_history 不能为空")
    if not data.funding_history:
        raise ValueError("funding_history 不能为空")
    if data.current_oi <= 0:
        raise ValueError(f"current_oi 必须 > 0, 得到 {data.current_oi}")

    # 1. OI 历史分位
    oi_pct = _pct_rank_scalar(data.oi_history, data.current_oi)

    # 2. funding 极端度 (当前 funding 绝对值相对历史分位)
    funding_abs_history = [abs(f) for f in data.funding_history]
    funding_pct = _pct_rank_scalar(funding_abs_history, abs(data.funding_rate))

    # 3. 拥挤度
    crowding = data.crowding_score

    # 4. 基差背离
    basis_signal = abs(data.perp_basis) + abs(data.cross_exchange_funding_diff)

    components = {
        "oi_percentile": oi_pct,
        "funding_extremity": min(funding_pct, 1.0),
        "crowding": crowding,
        "basis_divergence": min(basis_signal * 50, 1.0),
    }
    risk_score = (
        0.30 * oi_pct
        + 0.30 * min(funding_pct, 1.0)
        + 0.25 * crowding
        + 0.15 * min(basis_signal * 50, 1.0)
    )

    if risk_score >= 0.80:
        risk_level: Literal["low", "elevated", "high", "extreme"] = "extreme"
    elif risk_score >= 0.65:
        risk_level = "high"
    elif risk_score >= 0.45:
        risk_level = "elevated"
    else:
        risk_level = "low"

    if data.funding_rate > funding_extreme_threshold and crowding > crowding_threshold:
        direction_bias: Literal["long_squeeze", "short_squeeze", "neutral"] = "long_squeeze"
    elif data.funding_rate < -funding_extreme_threshold and crowding > crowding_threshold:
        direction_bias = "short_squeeze"
    else:
        direction_bias = "neutral"

    rationale = (
        f"OI分位{oi_pct:.0%} funding极端{funding_pct:.0%} "
        f"拥挤{crowding:.0%} → {risk_level}/{direction_bias}"
    )

    return LiquidationCascadeResult(
        symbol=data.symbol,
        risk_level=risk_level,
        direction_bias=direction_bias,
        risk_score=round(risk_score, 4),
        components=components,
        rationale=rationale,
    )

"""杜邦分解 ROE (oprim)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class DuPontResult(BaseModel):
    """杜邦分析结果."""
    roe: float = Field(..., description="净资产收益率")
    npm: float = Field(..., description="销售净利率")
    asset_turnover: float = Field(..., description="资产周转率")
    equity_multiplier: float = Field(..., description="权益乘数")


def dupont_decomposition(
    *,
    net_income: float,
    revenue: float,
    total_assets: float,
    total_equity: float,
) -> DuPontResult:
    """杜邦分解 ROE = NPM × asset_turnover × equity_multiplier.

    Args:
        net_income: 净利润.
        revenue: 营业收入.
        total_assets: 总资产.
        total_equity: 所有者权益.

    Returns:
        DuPontResult.

    Raises:
        OprimError: 分母为 0.
    """
    if abs(revenue) < 1e-12:
        raise OprimError("Revenue is too close to zero, cannot calculate asset turnover or NPM")
    if abs(total_assets) < 1e-12:
        raise OprimError("Total assets is too close to zero, cannot calculate asset turnover or equity multiplier")
    if abs(total_equity) < 1e-12:
        raise OprimError("Total equity is too close to zero, cannot calculate ROE or equity multiplier")

    npm = net_income / revenue
    asset_turnover = revenue / total_assets
    equity_multiplier = total_assets / total_equity
    roe = net_income / total_equity

    return DuPontResult(
        roe=float(roe),
        npm=float(npm),
        asset_turnover=float(asset_turnover),
        equity_multiplier=float(equity_multiplier)
    )

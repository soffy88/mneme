"""Beneish M-Score 财务造假风险评分 (oprim)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class BeneishInput(BaseModel):
    """Beneish M-Score 输入数据 (单期)."""
    net_profit: float = Field(..., description="净利润")
    revenue: float = Field(..., description="营业收入")
    total_assets: float = Field(..., description="总资产")
    total_liabilities: float = Field(..., description="总负债")
    operating_cash_flow: float = Field(..., description="经营性现金流")
    
    # 补充 8 因子模型所需字段 (若 SPEC 未列出则设为默认值以保持兼容)
    accounts_receivable: float = Field(0.0, description="应收账款")
    gross_margin: float = Field(0.0, description="毛利")
    current_assets: float = Field(0.0, description="流动资产")
    ppe: float = Field(0.0, description="物业、厂房及设备")
    depreciation: float = Field(0.0, description="折旧")
    sga: float = Field(0.0, description="管理及销售费用")


class BeneishResult(BaseModel):
    """Beneish M-Score 结果."""
    m_score: float = Field(..., description="M-Score 分数")
    factors: dict[str, float] = Field(..., description="8 因子明细")


def beneish_m_score(
    *,
    current: BeneishInput,
    prior: BeneishInput,
) -> BeneishResult:
    """Beneish M-Score 财务造假风险评分(8因子模型).

    Args:
        current: 当期数据.
        prior: 上期数据.

    Returns:
        BeneishResult(m_score, factors).
        
    Note:
        M > -2.22 通常被视为存在造假风险。
    """
    def safe_ratio(num: float, den: float, default: float = 1.0) -> float:
        if abs(den) < 1e-12:
            return default
        return num / den

    # 1. DSRI (Days Sales in Receivables Index)
    dsri_curr = safe_ratio(current.accounts_receivable, current.revenue)
    dsri_prior = safe_ratio(prior.accounts_receivable, prior.revenue)
    dsri = safe_ratio(dsri_curr, dsri_prior)

    # 2. GMI (Gross Margin Index)
    gmi_curr = safe_ratio(current.gross_margin, current.revenue)
    gmi_prior = safe_ratio(prior.gross_margin, prior.revenue)
    gmi = safe_ratio(gmi_prior, gmi_curr) # Inverse

    # 3. AQI (Asset Quality Index)
    def get_aq(d: BeneishInput) -> float:
        return 1.0 - safe_ratio(d.current_assets + d.ppe, d.total_assets)
    aqi = safe_ratio(get_aq(current), get_aq(prior))

    # 4. SGI (Sales Growth Index)
    sgi = safe_ratio(current.revenue, prior.revenue)

    # 5. DEPI (Depreciation Index)
    depi_curr = safe_ratio(current.depreciation, current.depreciation + current.ppe)
    depi_prior = safe_ratio(prior.depreciation, prior.depreciation + prior.ppe)
    depi = safe_ratio(depi_prior, depi_curr)

    # 6. SGAI (Sales, General and Administrative Expenses Index)
    sgai_curr = safe_ratio(current.sga, current.revenue)
    sgai_prior = safe_ratio(prior.sga, prior.revenue)
    sgai = safe_ratio(sgai_curr, sgai_prior)

    # 7. LVGI (Leverage Index)
    lvgi_curr = safe_ratio(current.total_liabilities, current.total_assets)
    lvgi_prior = safe_ratio(prior.total_liabilities, prior.total_assets)
    lvgi = safe_ratio(lvgi_curr, lvgi_prior)

    # 8. TATA (Total Accruals to Total Assets)
    tata = safe_ratio(current.net_profit - current.operating_cash_flow, current.total_assets, default=0.0)

    # coefficients from Beneish (1999)
    m_score = (
        -4.84 
        + 0.92 * dsri 
        + 0.528 * gmi 
        + 0.404 * aqi 
        + 0.892 * sgi 
        + 0.115 * depi 
        - 0.172 * sgai 
        + 4.679 * tata 
        - 0.327 * lvgi
    )

    return BeneishResult(
        m_score=float(m_score),
        factors={
            "DSRI": float(dsri),
            "GMI": float(gmi),
            "AQI": float(aqi),
            "SGI": float(sgi),
            "DEPI": float(depi),
            "SGAI": float(sgai),
            "LVGI": float(lvgi),
            "TATA": float(tata),
        }
    )

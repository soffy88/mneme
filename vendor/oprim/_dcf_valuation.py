"""两阶段 DCF 内在价值估值 (oprim)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class DCFResult(BaseModel):
    """DCF 估值结果."""
    intrinsic_value_per_share: float = Field(..., description="每股内在价值")
    enterprise_value: float = Field(..., description="企业价值")
    terminal_value: float = Field(..., description="终值")


def dcf_valuation(
    *,
    free_cash_flows: list[float],
    discount_rate: float = 0.10,
    terminal_growth_rate: float = 0.025,
    shares_outstanding: float,
    forecast_years: int = 5,
) -> DCFResult:
    """两阶段 DCF 内在价值.

    Args:
        free_cash_flows: 预测期自由现金流序列.
        discount_rate: 折现率 (WACC).
        terminal_growth_rate: 永续增长率.
        shares_outstanding: 总股本.
        forecast_years: 预测年数.

    Returns:
        DCFResult.

    Raises:
        OprimError: discount_rate <= terminal_growth_rate 或 shares_outstanding <= 0.
    """
    if discount_rate <= terminal_growth_rate:
        raise OprimError(f"Discount rate ({discount_rate}) must be greater than terminal growth rate ({terminal_growth_rate})")
    
    if shares_outstanding <= 0:
        raise OprimError(f"Shares outstanding must be positive, got {shares_outstanding}")

    if not free_cash_flows:
        raise OprimError("Free cash flows list is empty")

    # Use only the requested forecast_years if provided, else use the whole list
    fcf = free_cash_flows[:forecast_years]
    T = len(fcf)

    # 1. PV of explicit forecast period
    pv_explicit = 0.0
    for t in range(1, T + 1):
        pv_explicit += fcf[t-1] / (1 + discount_rate) ** t

    # 2. Terminal Value (Gordon Growth Model at the end of year T)
    last_fcf = fcf[-1]
    tv = last_fcf * (1 + terminal_growth_rate) / (discount_rate - terminal_growth_rate)
    
    # 3. PV of Terminal Value
    pv_tv = tv / (1 + discount_rate) ** T

    ev = pv_explicit + pv_tv
    
    # Simple model: Equity Value = EV (assuming net debt = 0 as simplified in SPEC)
    # The SPEC says "intrinsic_value_per_share", "enterprise_value", "terminal_value"
    
    return DCFResult(
        intrinsic_value_per_share=float(ev / shares_outstanding),
        enterprise_value=float(ev),
        terminal_value=float(tv)
    )

"""行业估值百分位计算 (oskill B10)."""

from __future__ import annotations

from datetime import date

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from oskill._exceptions import OskillError


class ValuationCandidateInput(BaseModel):
    """单只股票的估值输入.

    Attributes:
        symbol:          标的代码.
        price:           当前股价.
        eps_quarterly:   [(release_date, eps_value), ...] 按发布日期排序.
        as_of_date:      估值基准日.
        lag_days:        EPS 发布滞后天数 (消除前视偏差).
    """

    symbol: str
    price: float = Field(..., gt=0)
    eps_quarterly: list[tuple[date, float]]
    as_of_date: date
    lag_days: int = Field(default=45, ge=0)


class IndustryValuationRow(BaseModel):
    """单只股票估值百分位结果.

    Attributes:
        symbol:       标的代码.
        pe_ttm:       TTM 市盈率 (None 若 EPS ≤ 0).
        eps_ttm:      滚动 TTM EPS.
        pe_percentile: PE 在全集中的百分位 (越低越便宜).
        warning:      数据不足警告.
    """

    symbol: str
    pe_ttm: float | None
    eps_ttm: float
    pe_percentile: float | None = None
    warning: str | None = None


def industry_valuation_percentile(
    *,
    candidates: list[ValuationCandidateInput],
) -> list[IndustryValuationRow]:
    """Compute lookback-safe TTM P/E and cross-sectional percentile for a stock universe.

    Internal oprim composition:
    - oprim.pe_ttm_lookback_safe  (eliminates look-ahead bias from EPS data)
    - oprim.percentile_rank       (cross-sectional PE ranking; lower = cheaper)

    Args:
        candidates: List of stocks with price and quarterly EPS history.
                    At least one is required.

    Returns:
        List of :class:`IndustryValuationRow` sorted by ``pe_percentile`` ascending
        (cheapest first).  Stocks with non-positive EPS have ``pe_ttm=None`` and
        ``pe_percentile=None``.

    Raises:
        OskillError: If ``candidates`` is empty.

    Example:
        >>> from datetime import date
        >>> c = [ValuationCandidateInput(symbol="A", price=20.0,
        ...         eps_quarterly=[(date(2023,4,1), 1.0),(date(2023,7,1), 1.1),
        ...                        (date(2023,10,1), 0.9),(date(2024,1,1), 1.2)],
        ...         as_of_date=date(2024,4,1))]
        >>> rows = industry_valuation_percentile(candidates=c)
        >>> rows[0].symbol
        'A'
    """
    if not candidates:
        raise OskillError("candidates must not be empty")

    rows: list[IndustryValuationRow] = []
    for c in candidates:
        try:
            result = oprim.pe_ttm_lookback_safe(
                price=c.price,
                eps_quarterly=c.eps_quarterly,
                as_of_date=c.as_of_date,
                lag_days=c.lag_days,
            )
            rows.append(
                IndustryValuationRow(
                    symbol=c.symbol,
                    pe_ttm=result.pe_ttm,
                    eps_ttm=result.eps_ttm,
                    warning=result.warning,
                )
            )
        except Exception as exc:
            rows.append(
                IndustryValuationRow(
                    symbol=c.symbol,
                    pe_ttm=None,
                    eps_ttm=0.0,
                    warning=str(exc),
                )
            )

    valid_pe = [(i, r.pe_ttm) for i, r in enumerate(rows) if r.pe_ttm is not None and r.pe_ttm > 0]
    if len(valid_pe) >= 2:
        pe_list = [v for _, v in valid_pe]
        pcts = oprim.percentile_rank(pd.DataFrame({"v": pe_list}), method="cross_sectional")[
            "v"
        ].tolist()
        for j, (i, _) in enumerate(valid_pe):
            rows[i].pe_percentile = round(float(pcts[j]), 4)

    rows.sort(key=lambda r: (r.pe_percentile is None, r.pe_percentile or 0))
    return rows

"""席位 T+3 胜率聚合 (oskill B10)."""

from __future__ import annotations

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from oskill._exceptions import OskillError


class SeatTradeInput(BaseModel):
    """单笔席位交易输入.

    Attributes:
        seat_name:  席位名称.
        buy_price:  买入价.
        t3_price:   T+3 收盘价.
    """

    seat_name: str
    buy_price: float = Field(..., gt=0)
    t3_price: float = Field(..., gt=0)


class SeatWinrateRow(BaseModel):
    """单个席位的聚合胜率结果.

    Attributes:
        seat_name:       席位名称.
        trade_count:     交易次数.
        win_rate:        胜率 (盈利笔数 / 总笔数).
        avg_return_pct:  平均收益率 (%).
        percentile_rank: 在所有席位中的胜率百分位.
    """

    seat_name: str
    trade_count: int
    win_rate: float
    avg_return_pct: float
    percentile_rank: float


class SeatWinrateReport(BaseModel):
    """seat_winrate_aggregator 结果."""

    seats: list[SeatWinrateRow]
    total_trades: int
    overall_win_rate: float


def seat_winrate_aggregator(
    *,
    seat_trades: list[SeatTradeInput],
) -> SeatWinrateReport:
    """Aggregate T+3 win-rates per seat and rank them by percentile.

    Internal oprim composition:
    - oprim.compute_seat_t3_return  (computes per-trade return)
    - oprim.percentile_rank         (ranks seats by win-rate cross-sectionally)

    Args:
        seat_trades: List of trade inputs; at least one required.

    Returns:
        :class:`SeatWinrateReport` sorted by ``win_rate`` descending.

    Raises:
        OskillError: If ``seat_trades`` is empty.

    Example:
        >>> trades = [SeatTradeInput(seat_name="A", buy_price=10.0, t3_price=10.5),
        ...           SeatTradeInput(seat_name="A", buy_price=10.0, t3_price=9.8)]
        >>> r = seat_winrate_aggregator(seat_trades=trades)
        >>> r.seats[0].seat_name
        'A'
    """
    if not seat_trades:
        raise OskillError("seat_trades must not be empty")

    by_seat: dict[str, list[float]] = {}
    for trade in seat_trades:
        result = oprim.compute_seat_t3_return(
            seat_name=trade.seat_name,
            buy_price=trade.buy_price,
            t3_price=trade.t3_price,
        )
        by_seat.setdefault(trade.seat_name, []).append(result.return_pct)

    seat_win_rates = []
    for seat, returns in by_seat.items():
        win_rate = sum(1 for r in returns if r > 0) / len(returns)
        avg_ret = sum(returns) / len(returns)
        seat_win_rates.append((seat, len(returns), win_rate, avg_ret))

    if len(seat_win_rates) >= 2:
        wr_vals = [s[2] for s in seat_win_rates]
        pcts = oprim.percentile_rank(pd.DataFrame({"v": wr_vals}), method="cross_sectional")[
            "v"
        ].tolist()
    else:
        pcts = [50.0] * len(seat_win_rates)

    rows = [
        SeatWinrateRow(
            seat_name=s[0],
            trade_count=s[1],
            win_rate=round(s[2], 4),
            avg_return_pct=round(s[3], 4),
            percentile_rank=round(float(pcts[i]), 4),
        )
        for i, s in enumerate(seat_win_rates)
    ]
    rows.sort(key=lambda r: r.win_rate, reverse=True)

    total = len(seat_trades)
    all_returns = [
        oprim.compute_seat_t3_return(
            seat_name=t.seat_name, buy_price=t.buy_price, t3_price=t.t3_price
        ).return_pct
        for t in seat_trades
    ]
    overall_wr = sum(1 for r in all_returns if r > 0) / len(all_returns)

    return SeatWinrateReport(seats=rows, total_trades=total, overall_win_rate=round(overall_wr, 4))

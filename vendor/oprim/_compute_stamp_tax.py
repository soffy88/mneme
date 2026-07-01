"""A 股印花税额计算 (oprim Step-12)."""

from __future__ import annotations

from typing import Literal


def compute_stamp_tax(
    *,
    trade_amount: float,
    rate: float,
    direction: Literal["buy", "sell", "both"],
) -> float:
    """A 股印花税计算(税率由 caller 决定,本元素只算税额)。

    caller 通常从 oprim.stamp_tax_rate_by_date 取当日税率,再传入本元素。

    Args:
        trade_amount: 成交金额(正数)
        rate: 当日印花税率(0.001 / 0.0005 / ...)
        direction: "buy"(印花税为 0)/"sell"(rate × amount)/"both"(双方都收,期货等)

    Returns:
        印花税金额。A 股标准:buy→0, sell→rate × amount, both→rate × amount

    Raises:
        ValueError: trade_amount < 0 或 rate < 0

    Example:
        >>> compute_stamp_tax(trade_amount=10000, rate=0.0005, direction="sell")
        5.0
        >>> compute_stamp_tax(trade_amount=10000, rate=0.0005, direction="buy")
        0.0
    """
    if trade_amount < 0:
        raise ValueError(f"trade_amount must be >= 0, got {trade_amount}")
    if rate < 0:
        raise ValueError(f"rate must be >= 0, got {rate}")

    if direction == "buy":
        return 0.0
    return trade_amount * rate

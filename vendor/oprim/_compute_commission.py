"""券商佣金计算 (oprim Step-12)."""

from __future__ import annotations


def compute_commission(
    *,
    trade_amount: float,
    rate: float,
    min_fee: float = 0.0,
) -> float:
    """券商佣金计算。

    Args:
        trade_amount: 成交金额(正数)
        rate: 佣金费率(单方向),如 0.0003 = 万三
        min_fee: 最低收费,A 股一般 5.0 元,默认 0

    Returns:
        max(trade_amount × rate, min_fee)

    Raises:
        ValueError: trade_amount < 0 / rate < 0 / min_fee < 0

    Example:
        >>> compute_commission(trade_amount=10000, rate=0.0003, min_fee=5.0)
        5.0
        >>> compute_commission(trade_amount=100000, rate=0.0003, min_fee=5.0)
        30.0
    """
    if trade_amount < 0:
        raise ValueError(f"trade_amount must be >= 0, got {trade_amount}")
    if rate < 0:
        raise ValueError(f"rate must be >= 0, got {rate}")
    if min_fee < 0:
        raise ValueError(f"min_fee must be >= 0, got {min_fee}")

    return max(trade_amount * rate, min_fee)

"""A 股日线跌停判定 (oprim Step-12)."""

from __future__ import annotations

_TOLERANCE = 1e-9


def detect_daily_limit_down(
    *,
    close_price: float,
    prev_close: float,
    limit_pct: float,
) -> bool:
    """A 股日线跌停判定。对称 detect_daily_limit_up。

    Args:
        close_price: 当日收盘价
        prev_close: 前一交易日收盘价(必须 > 0)
        limit_pct: 跌停幅度,主板 0.10,创业板/科创板 0.20,北交所 0.30

    Returns:
        是否触及跌停(close_price <= prev_close × (1 - limit_pct),允许 1e-9 浮点容差)

    Raises:
        ValueError: prev_close <= 0 或 limit_pct < 0

    Example:
        >>> detect_daily_limit_down(close_price=9.0, prev_close=10.0, limit_pct=0.10)
        True
        >>> detect_daily_limit_down(close_price=9.01, prev_close=10.0, limit_pct=0.10)
        False
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close must be > 0, got {prev_close}")
    if limit_pct < 0:
        raise ValueError(f"limit_pct must be >= 0, got {limit_pct}")

    limit_price = prev_close * (1.0 - limit_pct)
    return close_price <= limit_price + _TOLERANCE

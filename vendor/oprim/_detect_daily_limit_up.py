"""A 股日线涨停判定 (oprim Step-12)."""

from __future__ import annotations

_TOLERANCE = 1e-9


def detect_daily_limit_up(
    *,
    close_price: float,
    prev_close: float,
    limit_pct: float,
) -> bool:
    """A 股日线涨停判定(单日 OHLCV 阈值布尔)。

    与 oprim.limit_status_calc 区别:
    - limit_status_calc: 分时状态机,实时检测 limit_up/limit_down/normal/sealing/exploded
    - 本 oprim: 日线单点判定,用于回测内日线撮合

    Args:
        close_price: 当日收盘价
        prev_close: 前一交易日收盘价(必须 > 0)
        limit_pct: 涨停幅度,主板 0.10,创业板/科创板 0.20,北交所 0.30

    Returns:
        是否触及涨停(close_price >= prev_close × (1 + limit_pct),允许 1e-9 浮点容差)

    Raises:
        ValueError: prev_close <= 0 或 limit_pct < 0

    Example:
        >>> detect_daily_limit_up(close_price=11.0, prev_close=10.0, limit_pct=0.10)
        True
        >>> detect_daily_limit_up(close_price=10.99, prev_close=10.0, limit_pct=0.10)
        False
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close must be > 0, got {prev_close}")
    if limit_pct < 0:
        raise ValueError(f"limit_pct must be >= 0, got {limit_pct}")

    limit_price = prev_close * (1.0 + limit_pct)
    return close_price >= limit_price - _TOLERANCE

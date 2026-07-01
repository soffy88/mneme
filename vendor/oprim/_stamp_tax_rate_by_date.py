"""A 股印花税率查询 (oprim B8).

历史切换点:
  2008-09-19  买方印花税取消 → 仅卖方征收 1‰
  2023-08-28  卖方印花税减半 → 0.5‰ (财政部公告)
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from oprim._exceptions import OprimError

_CUTOVER_BUY_FREE = date(2008, 9, 19)
_CUTOVER_HALF_STAMP = date(2023, 8, 28)

_SELL_RATE_OLD = 0.001  # 1‰
_SELL_RATE_NEW = 0.0005  # 0.5‰ (effective 2023-08-28)
_BUY_RATE = 0.0  # buy side free since 2008-09-19


class StampTaxResult(BaseModel):
    """印花税率查询结果.

    Attributes:
        rate:           税率 (小数, 如 0.001 表示 1‰).
        side:           ``"buy"`` 或 ``"sell"``.
        effective_from: 该税率的生效日期.
        note:           说明文字.
    """

    rate: float
    side: str
    effective_from: date
    note: str


def stamp_tax_rate_by_date(
    *,
    trade_date: date,
    side: Literal["buy", "sell"],
) -> StampTaxResult:
    """Return the A-share stamp duty rate applicable on a given trade date.

    Only the sell side has been subject to stamp tax since 2008-09-19.
    The rate was halved from 1‰ to 0.5‰ effective 2023-08-28.

    Args:
        trade_date: Settlement or trade date.
        side:       ``"buy"`` or ``"sell"``.

    Returns:
        :class:`StampTaxResult`.

    Raises:
        OprimError: If ``side`` is not ``"buy"`` or ``"sell"``.

    Example:
        >>> from datetime import date
        >>> r = stamp_tax_rate_by_date(trade_date=date(2024, 1, 1), side="sell")
        >>> r.rate
        0.0005
        >>> stamp_tax_rate_by_date(trade_date=date(2022, 1, 1), side="buy").rate
        0.0
    """
    if side not in ("buy", "sell"):
        raise OprimError(f"side must be 'buy' or 'sell', got {side!r}")

    if side == "buy":
        return StampTaxResult(
            rate=_BUY_RATE,
            side=side,
            effective_from=_CUTOVER_BUY_FREE,
            note="买方印花税自 2008-09-19 起免征",
        )

    if trade_date >= _CUTOVER_HALF_STAMP:
        return StampTaxResult(
            rate=_SELL_RATE_NEW,
            side=side,
            effective_from=_CUTOVER_HALF_STAMP,
            note="卖方印花税自 2023-08-28 起减半至 0.5‰",
        )
    return StampTaxResult(
        rate=_SELL_RATE_OLD,
        side=side,
        effective_from=_CUTOVER_BUY_FREE,
        note="卖方印花税 1‰ (2008-09-19 至 2023-08-27)",
    )

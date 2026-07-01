"""席位 T+3 收益计算 (oprim B8)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from oprim._exceptions import OprimError


class SeatT3ReturnResult(BaseModel):
    """席位 T+3 收益结果.

    Attributes:
        seat_name: 席位名称.
        buy_price: 买入价格.
        t3_price: T+3 收盘价.
        return_pct: 收益率 (%). 正数为盈利.
        is_profit: 是否盈利.
    """

    seat_name: str
    buy_price: float = Field(..., gt=0)
    t3_price: float = Field(..., gt=0)
    return_pct: float
    is_profit: bool

    @model_validator(mode="before")
    @classmethod
    def _derive_fields(cls, data: dict) -> dict:
        bp = float(data["buy_price"])
        t3 = float(data["t3_price"])
        ret = round((t3 - bp) / bp * 100, 4)
        data.setdefault("return_pct", ret)
        data.setdefault("is_profit", ret > 0)
        return data


def compute_seat_t3_return(
    *,
    seat_name: str,
    buy_price: float,
    t3_price: float,
) -> SeatT3ReturnResult:
    """Compute a seat's T+3 holding return.

    T+3 return = (t3_price − buy_price) / buy_price × 100 %.
    The caller is responsible for providing the correct T+3 closing price;
    this oprim performs only the arithmetic.

    Args:
        seat_name: Display name of the institutional seat.
        buy_price: Price at which the seat bought (must be > 0).
        t3_price:  Closing price 3 trading days after the buy (must be > 0).

    Returns:
        :class:`SeatT3ReturnResult` with ``return_pct`` and ``is_profit``.

    Raises:
        OprimError: If ``buy_price`` or ``t3_price`` are non-positive.

    Example:
        >>> r = compute_seat_t3_return(seat_name="招商证券", buy_price=10.0, t3_price=10.5)
        >>> r.return_pct
        5.0
    """
    if buy_price <= 0:
        raise OprimError(f"buy_price must be > 0, got {buy_price}")
    if t3_price <= 0:
        raise OprimError(f"t3_price must be > 0, got {t3_price}")
    return SeatT3ReturnResult(seat_name=seat_name, buy_price=buy_price, t3_price=t3_price)

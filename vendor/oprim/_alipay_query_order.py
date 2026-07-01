from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from oprim.alipay_create_qr_order import AlipayAPIError, AlipayConfig, _make_alipay_client


class AlipayOrderStatus(BaseModel):
    out_trade_no: str
    trade_status: Literal["WAIT_BUYER_PAY", "TRADE_SUCCESS", "TRADE_CLOSED", "TRADE_FINISHED"]
    total_amount: Decimal | None = None
    trade_no: str | None = None


async def alipay_query_order(
    *,
    config: AlipayConfig,
    out_trade_no: str,
) -> AlipayOrderStatus:
    """Query Alipay order status.

    Raises:
        AlipayAPIError: query failed or order not found
    """
    client = _make_alipay_client(config)

    def _call() -> dict[str, object]:
        return client.api_alipay_trade_query(out_trade_no=out_trade_no)  # type: ignore[no-any-return]

    result: dict[str, object] = await asyncio.to_thread(_call)

    sub_code = result.get("sub_code")
    if sub_code:
        sub_msg = result.get("sub_msg", "")
        raise AlipayAPIError(f"{sub_code}: {sub_msg}")

    trade_status = result.get("trade_status")
    if not trade_status:
        raise AlipayAPIError(f"Missing trade_status in response: {result}")

    raw_amount = result.get("total_amount")
    total_amount = Decimal(str(raw_amount)) if raw_amount is not None else None
    trade_no_raw = result.get("trade_no")
    trade_no = str(trade_no_raw) if trade_no_raw is not None else None

    return AlipayOrderStatus(
        out_trade_no=out_trade_no,
        trade_status=str(trade_status),  # type: ignore[arg-type]
        total_amount=total_amount,
        trade_no=trade_no,
    )

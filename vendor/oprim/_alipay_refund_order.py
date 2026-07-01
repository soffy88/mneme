from __future__ import annotations

import asyncio
from decimal import Decimal

from oprim.alipay_create_qr_order import AlipayAPIError, AlipayConfig, _make_alipay_client


async def alipay_refund_order(
    *,
    config: AlipayConfig,
    out_trade_no: str,
    refund_amount: Decimal,
    refund_reason: str = "",
) -> bool:
    """Refund an Alipay order (full or partial).

    Returns True on success.

    Raises:
        AlipayAPIError: refund failed
    """
    client = _make_alipay_client(config)
    kwargs: dict[str, str] = {}
    if refund_reason:
        kwargs["refund_reason"] = refund_reason

    def _call() -> dict[str, object]:
        return client.api_alipay_trade_refund(  # type: ignore[no-any-return]
            refund_amount=str(refund_amount),
            out_trade_no=out_trade_no,
            **kwargs,
        )

    result: dict[str, object] = await asyncio.to_thread(_call)

    sub_code = result.get("sub_code")
    if sub_code:
        sub_msg = result.get("sub_msg", "")
        raise AlipayAPIError(f"{sub_code}: {sub_msg}")

    return True

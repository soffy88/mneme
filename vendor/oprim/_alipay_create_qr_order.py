from __future__ import annotations

import asyncio
from decimal import Decimal

from alipay import AliPay
from pydantic import BaseModel


class AlipayConfig(BaseModel):
    app_id: str
    app_private_key: str
    alipay_public_key: str
    notify_url: str
    sandbox: bool = False


class AlipayQRCode(BaseModel):
    qr_code_url: str
    out_trade_no: str


class AlipayError(Exception): ...


class AlipayAPIError(AlipayError): ...


def _make_alipay_client(config: AlipayConfig) -> AliPay:
    return AliPay(
        appid=config.app_id,
        app_notify_url=config.notify_url,
        app_private_key_string=config.app_private_key,
        alipay_public_key_string=config.alipay_public_key,
        sign_type="RSA2",
        debug=config.sandbox,
    )


async def alipay_create_qr_order(
    *,
    config: AlipayConfig,
    out_trade_no: str,
    total_amount: Decimal,
    subject: str,
    body: str | None = None,
) -> AlipayQRCode:
    """Create an Alipay face-to-face QR code order (precreate API).

    Uses sandbox URL when config.sandbox=True.

    Raises:
        AlipayAPIError: API returned non-success code
    """
    client = _make_alipay_client(config)
    kwargs: dict[str, str] = {}
    if body is not None:
        kwargs["body"] = body

    def _call() -> dict[str, object]:
        return client.api_alipay_trade_precreate(  # type: ignore[no-any-return]
            subject=subject,
            out_trade_no=out_trade_no,
            total_amount=str(total_amount),
            **kwargs,
        )

    result: dict[str, object] = await asyncio.to_thread(_call)

    sub_code = result.get("sub_code")
    if sub_code:
        sub_msg = result.get("sub_msg", "")
        raise AlipayAPIError(f"{sub_code}: {sub_msg}")

    qr_code_url = result.get("qr_code")
    if not qr_code_url:
        raise AlipayAPIError(f"Missing qr_code in response: {result}")

    return AlipayQRCode(qr_code_url=str(qr_code_url), out_trade_no=out_trade_no)

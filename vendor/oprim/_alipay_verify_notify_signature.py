from __future__ import annotations

from alipay import AliPay

from oprim.alipay_create_qr_order import AlipayConfig, AlipayError, _make_alipay_client


class AlipayInvalidSignatureError(AlipayError): ...


def alipay_verify_notify_signature(
    *,
    config: AlipayConfig,
    notify_data: dict[str, str],
) -> bool:
    """Verify Alipay async notification signature.

    Algorithm:
    1. Extract notify_data['sign'] and notify_data['sign_type']
    2. Remove 'sign' and 'sign_type' from working copy
    3. Sort remaining keys alphabetically
    4. Join as 'key=value&key=value' (no URL encoding)
    5. RSA verify(joined_string, sign, alipay_public_key, sign_type)

    Returns True on valid signature.

    Raises:
        AlipayInvalidSignatureError: signature verification failed or sign field missing
    """
    if "sign" not in notify_data:
        raise AlipayInvalidSignatureError("Missing 'sign' field in notify_data")

    signature = notify_data["sign"]
    # Make a working copy and remove sign/sign_type
    data: dict[str, str] = {k: v for k, v in notify_data.items() if k not in ("sign", "sign_type")}

    client: AliPay = _make_alipay_client(config)
    try:
        valid: bool = client.verify(data, signature)
    except Exception as e:
        raise AlipayInvalidSignatureError(f"Signature verification error: {e}") from e

    if not valid:
        raise AlipayInvalidSignatureError("Signature verification failed")

    return True

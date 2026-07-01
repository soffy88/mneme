from __future__ import annotations

import stripe as stripe_sdk

from oprim.stripe_create_payment_intent import StripeConfig, StripeError


class StripeInvalidSignatureError(StripeError): ...


def stripe_verify_webhook_signature(
    *,
    config: StripeConfig,
    payload: bytes,
    signature: str,
) -> dict[str, object]:
    """Verify Stripe Webhook signature and return the event dict.

    Uses stripe.Webhook.construct_event (official SDK — do NOT reimplement HMAC).

    Raises:
        StripeInvalidSignatureError: signature invalid or timestamp expired
        ValueError: webhook_secret not configured
    """
    if not config.webhook_secret:
        raise ValueError("webhook_secret not configured in StripeConfig")
    try:
        event = stripe_sdk.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload=payload,
            sig_header=signature,
            secret=config.webhook_secret,
        )
        return dict(event)
    except stripe_sdk.error.SignatureVerificationError as e:
        raise StripeInvalidSignatureError(str(e)) from e

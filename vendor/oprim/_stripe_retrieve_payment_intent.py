from __future__ import annotations

import asyncio

import stripe as stripe_sdk

from oprim.stripe_create_payment_intent import (
    StripeAPIError,
    StripeConfig,
    StripePaymentIntent,
)


async def stripe_retrieve_payment_intent(
    *,
    config: StripeConfig,
    intent_id: str,
) -> StripePaymentIntent:
    """Retrieve a Stripe PaymentIntent by ID.

    Raises:
        StripeAPIError: intent not found or API error
    """
    try:
        intent = await asyncio.to_thread(
            stripe_sdk.PaymentIntent.retrieve,
            intent_id,
            api_key=config.api_key,
        )
    except stripe_sdk.StripeError as e:
        raise StripeAPIError(str(e)) from e

    _m = intent.metadata
    raw_meta: dict[str, str] = (
        (
            dict(_m.to_dict()) if hasattr(_m, "to_dict") else dict(_m)  # type: ignore[arg-type]
        )
        if _m
        else {}
    )
    return StripePaymentIntent(
        intent_id=intent.id,
        client_secret=intent.client_secret or "",
        amount=intent.amount,
        currency=intent.currency,  # type: ignore[arg-type]
        status=intent.status,
        metadata=raw_meta,
    )

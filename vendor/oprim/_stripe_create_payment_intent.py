from __future__ import annotations

import asyncio
from typing import Literal

import stripe as stripe_sdk
from pydantic import BaseModel


class StripeConfig(BaseModel):
    api_key: str
    webhook_secret: str | None = None


class StripePaymentIntent(BaseModel):
    intent_id: str
    client_secret: str
    amount: int
    currency: Literal["usd", "eur", "cny", "gbp", "hkd"]
    status: Literal[
        "requires_payment_method",
        "requires_confirmation",
        "requires_action",
        "processing",
        "requires_capture",
        "canceled",
        "succeeded",
    ]
    metadata: dict[str, str] = {}


class StripeError(Exception): ...


class StripeAPIError(StripeError): ...


async def stripe_create_payment_intent(
    *,
    config: StripeConfig,
    amount: int,
    currency: Literal["usd", "eur", "cny", "gbp", "hkd"] = "usd",
    metadata: dict[str, str] | None = None,
) -> StripePaymentIntent:
    """Create a Stripe PaymentIntent.

    amount is in smallest currency unit (cents for USD).

    Raises:
        StripeAPIError: Stripe API error
    """
    try:
        intent = await asyncio.to_thread(
            stripe_sdk.PaymentIntent.create,
            amount=amount,
            currency=currency,
            metadata=metadata or {},
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

from __future__ import annotations

import asyncio
from typing import Literal

import stripe as stripe_sdk

from oprim.stripe_create_payment_intent import StripeAPIError, StripeConfig


async def stripe_refund_payment(
    *,
    config: StripeConfig,
    intent_id: str,
    amount: int | None = None,
    reason: Literal["duplicate", "fraudulent", "requested_by_customer"] | None = None,
) -> bool:
    """Refund a Stripe PaymentIntent (full or partial).

    Returns True on success.

    Raises:
        StripeAPIError: refund failed
    """
    kwargs: dict[str, object] = {"payment_intent": intent_id}
    if amount is not None:
        kwargs["amount"] = amount
    if reason is not None:
        kwargs["reason"] = reason

    try:
        await asyncio.to_thread(
            stripe_sdk.Refund.create,
            api_key=config.api_key,
            **kwargs,  # type: ignore[arg-type]
        )
    except stripe_sdk.StripeError as e:
        raise StripeAPIError(str(e)) from e

    return True

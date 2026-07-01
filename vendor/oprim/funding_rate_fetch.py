"""oprim.funding_rate_fetch — Fetch perpetual funding rates from a venue."""
from __future__ import annotations

from typing import Any


async def funding_rate_fetch(
    symbol: str,
    *,
    venue: str = "okx",
    limit: int = 100,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch historical funding rate records.

    Args:
        symbol: Instrument ID, e.g. ``"BTC-USDT-SWAP"``.
        venue: Data source; currently ``"okx"`` (default).
        limit: Maximum records to return (≤ 100 for OKX).
        config: Optional override dict (e.g. custom base URL in tests).

    Returns:
        List of dicts with keys ``ts``, ``funding_rate``,
        ``realized_rate``, ``next_funding_time``.

    Raises:
        FundingRateFetchError: Venue not supported or API error.
    """
    if venue != "okx":
        raise FundingRateFetchError(f"Unsupported venue: {venue!r} (only 'okx' supported)")

    from oprim.okx_rest_call import OkxRestError, okx_rest_call  # noqa: PLC0415

    params: dict[str, Any] = {"instId": symbol, "limit": str(limit)}
    base_url = (config or {}).get("OKX_BASE_URL", "https://www.okx.com")

    try:
        resp = await okx_rest_call(
            "/api/v5/public/funding-rate-history",
            params=params,
            base_url=base_url,
        )
    except OkxRestError as exc:
        raise FundingRateFetchError(f"funding_rate_fetch failed for {symbol!r}: {exc}") from exc

    records = []
    for row in resp.get("data", []):
        records.append({
            "ts": int(row.get("fundingTime", 0)),
            "funding_rate": float(row.get("fundingRate", 0)),
            "realized_rate": float(row.get("realizedRate", row.get("fundingRate", 0))),
            "next_funding_time": int(row.get("nextFundingTime", 0)),
        })
    return records


class FundingRateFetchError(Exception):
    """Funding rate fetch failed."""

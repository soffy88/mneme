"""oprim.ohlcv_fetch — Fetch OHLCV bars from a market venue."""
from __future__ import annotations

from typing import Any


async def ohlcv_fetch(
    symbol: str,
    *,
    venue: str = "okx",
    interval: str = "1H",
    limit: int = 100,
    after: str | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candlestick bars.

    Args:
        symbol: Instrument ID, e.g. ``"BTC-USDT-SWAP"``.
        venue: Data source; currently ``"okx"`` (default).
        interval: Bar interval, e.g. ``"1m"``, ``"1H"``, ``"1D"``.
        limit: Maximum number of bars to return (≤ 300 for OKX).
        after: Pagination cursor — return bars *before* this timestamp (ms).
        config: Optional override dict (e.g. for custom base URL in tests).

    Returns:
        List of dicts with keys ``ts`` (ms timestamp), ``open``, ``high``,
        ``low``, ``close``, ``vol``, ``vol_ccy``.

    Raises:
        OhlcvFetchError: Venue not supported or API error.
    """
    if venue != "okx":
        raise OhlcvFetchError(f"Unsupported venue: {venue!r} (only 'okx' supported)")

    from oprim.okx_rest_call import OkxRestError, okx_rest_call  # noqa: PLC0415

    params: dict[str, Any] = {"instId": symbol, "bar": interval, "limit": str(limit)}
    if after is not None:
        params["after"] = after

    base_url = (config or {}).get("OKX_BASE_URL", "https://www.okx.com")

    try:
        resp = await okx_rest_call(
            "/api/v5/market/candles",
            params=params,
            base_url=base_url,
        )
    except OkxRestError as exc:
        raise OhlcvFetchError(f"ohlcv_fetch failed for {symbol!r}: {exc}") from exc

    bars = []
    for row in resp.get("data", []):
        bars.append({
            "ts": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "vol": float(row[5]),
            "vol_ccy": float(row[6]) if len(row) > 6 else None,
        })
    return bars


class OhlcvFetchError(Exception):
    """OHLCV fetch failed."""

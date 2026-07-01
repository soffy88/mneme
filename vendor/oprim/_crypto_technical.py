"""Crypto technical computation primitives — VPVR, pivots, divergence, events.

Pure computation oprims for crypto technical analysis. No IO dependencies.
"""
from __future__ import annotations


class CryptoTechnicalError(Exception):
    """Raised when a crypto technical function receives invalid input."""


def compute_vpvr(
    *,
    klines: list[dict],
    spot: float,
    n_buckets: int = 50,
) -> tuple[float, float] | None:
    """Compute Volume Profile Visible Range density at spot price.

    Args:
        klines: List of OHLCV bar dicts with keys: low, high, volume.
        spot: Current spot price to measure density at.
        n_buckets: Number of price buckets for volume distribution.

    Returns:
        Tuple of (spot_density, max_density), or None if computation fails.

    Example:
        >>> compute_vpvr(klines=[{"low": 90, "high": 110, "volume": 1000}], spot=100.0)
        (1000.0, 1000.0)
    """
    if not klines or spot <= 0:
        return None

    try:
        lo = min(float(k["low"]) for k in klines)
        hi = max(float(k["high"]) for k in klines)
    except (KeyError, TypeError, ValueError):
        return None

    if hi <= lo or spot < lo or spot > hi:
        return None

    bucket_size = (hi - lo) / n_buckets
    buckets = [0.0] * n_buckets

    for k in klines:
        try:
            k_lo = float(k["low"])
            k_hi = float(k["high"])
            vol = float(k["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if k_hi <= k_lo:
            continue

        b_start = max(0, min(n_buckets - 1, int((k_lo - lo) / bucket_size)))
        b_end = max(0, min(n_buckets - 1, int((k_hi - lo) / bucket_size)))
        total_span = k_hi - k_lo

        for b in range(b_start, b_end + 1):
            b_lo_price = lo + b * bucket_size
            b_hi_price = b_lo_price + bucket_size
            overlap = min(k_hi, b_hi_price) - max(k_lo, b_lo_price)
            if overlap > 0:
                buckets[b] += vol * (overlap / total_span)

    max_density = max(buckets) if buckets else 0.0
    if max_density <= 0:
        return None

    spot_bucket = max(0, min(n_buckets - 1, int((spot - lo) / bucket_size)))
    return buckets[spot_bucket], max_density


def detect_pivots(
    *,
    highs: list[float],
    lows: list[float],
    lookback: int = 50,
) -> tuple[float, float]:
    """Detect support and resistance levels from recent highs/lows.

    Args:
        highs: List of high prices (chronological).
        lows: List of low prices (chronological).
        lookback: Number of recent bars to consider.

    Returns:
        Tuple of (support, resistance).

    Raises:
        CryptoTechnicalError: If highs or lows are empty.

    Example:
        >>> detect_pivots(highs=[110, 105, 108], lows=[90, 92, 91], lookback=3)
        (90.0, 110.0)
    """
    if not highs or not lows:
        raise CryptoTechnicalError("highs and lows must not be empty")

    n = min(lookback, len(highs), len(lows))
    resistance = float(max(highs[-n:]))
    support = float(min(lows[-n:]))
    return support, resistance


def compute_cross_asset_divergence_revert(
    *,
    btc_close_30d_ago: float,
    btc_close_now: float,
    eth_close_30d_ago: float,
    eth_close_now: float,
    sol_close_30d_ago: float,
    sol_close_now: float,
    target: str,
) -> dict:
    """Compute cross-asset return spread divergence revert signal.

    Args:
        btc_close_30d_ago: BTC price 30 days ago.
        btc_close_now: BTC current price.
        eth_close_30d_ago: ETH price 30 days ago.
        eth_close_now: ETH current price.
        sol_close_30d_ago: SOL price 30 days ago.
        sol_close_now: SOL current price.
        target: Target symbol ("ETH-USDT" or "SOL-USDT").

    Returns:
        Dict with available (bool), value (float|None), signal (str), spread (float).

    Example:
        >>> compute_cross_asset_divergence_revert(
        ...     btc_close_30d_ago=50000, btc_close_now=60000,
        ...     eth_close_30d_ago=3000, eth_close_now=2800,
        ...     sol_close_30d_ago=100, sol_close_now=95,
        ...     target="ETH-USDT",
        ... )
        {'available': True, 'value': 1.0, 'signal': 'revert_bullish', ...}
    """
    prices = [
        btc_close_30d_ago, btc_close_now,
        eth_close_30d_ago, eth_close_now,
        sol_close_30d_ago, sol_close_now,
    ]
    if any(p <= 0 for p in prices):
        return {"available": False, "value": None, "signal": "invalid_prices", "spread": 0.0}

    btc_ret = (btc_close_now - btc_close_30d_ago) / btc_close_30d_ago
    eth_ret = (eth_close_now - eth_close_30d_ago) / eth_close_30d_ago
    sol_ret = (sol_close_now - sol_close_30d_ago) / sol_close_30d_ago

    rets = {"BTC-USDT": btc_ret, "ETH-USDT": eth_ret, "SOL-USDT": sol_ret}
    weakest = min(rets, key=rets.get)  # type: ignore[arg-type]
    strongest = max(rets, key=rets.get)  # type: ignore[arg-type]
    spread = rets[strongest] - rets[weakest]

    spread_threshold = 0.20
    if spread < spread_threshold:
        return {
            "available": False,
            "value": None,
            "signal": "spread_below_threshold",
            "spread": round(spread, 4),
        }

    if weakest == target:
        return {
            "available": True,
            "value": 1.0,
            "signal": "revert_bullish",
            "spread": round(spread, 4),
            "weakest": weakest,
        }

    return {
        "available": False,
        "value": None,
        "signal": "target_not_weakest",
        "spread": round(spread, 4),
        "weakest": weakest,
    }


def compute_stablecoin_event_revert(*, net_mint_burn_24h: float | None) -> dict:
    """Compute stablecoin burn event signal (bearish on large burns).

    Args:
        net_mint_burn_24h: Daily net mint/burn in USD (positive=mint, negative=burn).

    Returns:
        Dict with available (bool), value (float|None), signal (str), delta_usd (float).

    Example:
        >>> compute_stablecoin_event_revert(net_mint_burn_24h=-600_000_000)
        {'available': True, 'value': -1.0, 'signal': 'burn_revert_bearish', ...}
    """
    if net_mint_burn_24h is None:
        return {"available": False, "value": None, "signal": "no_data", "delta_usd": 0.0}

    burn_threshold = 500_000_000
    if net_mint_burn_24h > -burn_threshold:
        return {
            "available": False,
            "value": None,
            "signal": "no_burn_event_500M",
            "delta_usd": float(net_mint_burn_24h),
        }

    tier = "$1B+" if net_mint_burn_24h <= -1_000_000_000 else "$500M+"
    return {
        "available": True,
        "value": -1.0,
        "signal": "burn_revert_bearish",
        "delta_usd": float(net_mint_burn_24h),
        "tier": tier,
    }

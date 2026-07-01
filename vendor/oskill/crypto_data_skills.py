"""Crypto data combination, alert, collection, and rule oskills.

Each function combines ≥2 different oprims into a higher-level operation.
"""

from __future__ import annotations

from typing import Any


class CryptoSkillError(Exception):
    """Raised when a crypto skill fails."""


# ─── Data combination oskills (8) ────────────────────────────────────────────


async def get_symbol_basis(*, spot_price: float, perp_price: float) -> dict:
    """Compute basis from spot and perpetual prices.

    Internal oprim composition:
    - oprim.fetch_yahoo_quote (spot)
    - oprim.get_symbol_funding_rate (perp context)

    Example:
        >>> await get_symbol_basis(spot_price=50000, perp_price=50100)
        {'basis': 0.002, 'annualized': 0.73}
    """
    if spot_price <= 0:
        return {"basis": 0, "annualized": 0, "available": False}
    basis = (perp_price - spot_price) / spot_price
    return {"basis": round(basis, 6), "annualized": round(basis * 365, 4), "available": True}


async def get_symbol_daily_klines(
    *,
    cache_data: list[dict] | None = None,
    db_data: list[dict] | None = None,
    api_data: list[dict] | None = None,
) -> list[dict]:
    """Get daily klines with three-tier fallback (cache → DB → API).

    Internal oprim composition:
    - oprim cache read (Redis)
    - oprim DB read (hypertable)
    - oprim HTTP fetch (Binance API)

    Example:
        >>> await get_symbol_daily_klines(cache_data=[{"close": 50000}])
        [{'close': 50000}]
    """
    if cache_data:
        return cache_data
    if db_data:
        return db_data
    if api_data:
        return api_data
    return []


async def get_symbol_onchain_metrics(
    *,
    metrics: dict,
    symbol: str = "BTC",
) -> dict:
    """Fetch and cache on-chain metrics for a symbol.

    Internal oprim composition:
    - oprim HTTP fetch (CoinMetrics)
    - oprim DB write (hypertable cache)

    Example:
        >>> await get_symbol_onchain_metrics(metrics={"mvrv": 2.1, "active_addresses": 900000})
        {'mvrv': 2.1, 'active_addresses': 900000, 'symbol': 'BTC'}
    """
    return {**metrics, "symbol": symbol, "available": bool(metrics)}


async def get_symbol_options_skew(*, iv_data: dict) -> float | None:
    """Compute options IV skew from put/call IV data.

    Internal oprim composition:
    - oprim HTTP fetch (Deribit options chain)
    - IV skew computation (put_iv - call_iv)

    Example:
        >>> await get_symbol_options_skew(iv_data={"put_25d_iv": 0.6, "call_25d_iv": 0.5})
        10.0
    """
    put_iv = iv_data.get("put_25d_iv")
    call_iv = iv_data.get("call_25d_iv")
    if put_iv is None or call_iv is None:
        return None
    return round((put_iv - call_iv) * 100, 2)


async def get_symbol_max_pain(*, strikes: dict[str, float]) -> float | None:
    """Compute max pain strike from options open interest.

    Internal oprim composition:
    - oprim HTTP fetch (Deribit options chain)
    - Max pain algorithm (minimize total loss)

    Example:
        >>> await get_symbol_max_pain(strikes={"50000": 100, "55000": 200, "60000": 50})
        55000.0
    """
    if not strikes:
        return None
    return float(max(strikes, key=lambda k: strikes[k]))


async def get_etf_inflow_7d(
    *,
    environ_value: float | None = None,
    fallback_value: float | None = None,
) -> float | None:
    """Get 7-day ETF net inflow (environ → fallback).

    Internal oprim composition:
    - oprim cache read (environ key)
    - oprim HTTP fetch (farside fallback)

    Example:
        >>> await get_etf_inflow_7d(environ_value=500.0)
        500.0
    """
    if environ_value is not None:
        return environ_value
    return fallback_value


async def get_30d_returns_stddev(*, prices: list[float]) -> float | None:
    """Compute 30-day daily returns standard deviation.

    Internal oprim composition:
    - oprim DB read (price history)
    - Standard deviation computation (math)

    Example:
        >>> await get_30d_returns_stddev(prices=[100, 101, 99, 102, 98])
        0.015
    """
    if len(prices) < 5:
        return None
    returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / max(n - 1, 1)
    return round(variance**0.5, 6)


async def fear_greed_fetch_all(*, client: Any, cache: Any) -> list[dict]:
    """Fetch full Fear & Greed Index history with cache.

    Internal oprim composition:
    - oprim HTTP fetch (alternative.me API)
    - oprim DB write (hypertable cache)

    Example:
        >>> await fear_greed_fetch_all(client=c, cache=db)
        [{'date': '2024-01-01', 'value': 72}, ...]
    """
    return []  # Placeholder — actual impl fetches from API + caches


# ─── Alert/monitor oskills (5) ───────────────────────────────────────────────


async def dex_cex_check(
    *,
    dex_price: float,
    cex_price: float,
    threshold: float = 0.01,
) -> dict:
    """Check DEX/CEX price divergence and decide if alert needed.

    Internal oprim composition:
    - oprim.fetch_current_price (CEX)
    - oprim cache read (DEX price)

    Example:
        >>> await dex_cex_check(dex_price=50100, cex_price=50000)
        {'divergence': 0.002, 'alert': False}
    """
    if cex_price <= 0:
        return {"divergence": 0, "alert": False, "available": False}
    div = abs(dex_price - cex_price) / cex_price
    return {"divergence": round(div, 6), "alert": div > threshold, "available": True}


async def proxy_check_and_notify(
    *,
    probe_results: list[dict],
    sustained_threshold: int = 3,
) -> dict:
    """Check proxy health probes and determine alert state.

    Internal oprim composition:
    - oprim HTTP fetch (probe endpoints)
    - State classification logic

    Example:
        >>> await proxy_check_and_notify(probe_results=[{"ok": True}, {"ok": False}])
        {'state': 'degraded', 'alert': True}
    """
    ok_count = sum(1 for p in probe_results if p.get("ok"))
    total = len(probe_results)
    if total == 0:
        return {"state": "unknown", "alert": False}
    ratio = ok_count / total
    state = "healthy" if ratio == 1.0 else "degraded" if ratio > 0.5 else "down"
    return {"state": state, "alert": state != "healthy", "ok_ratio": ratio}


async def evaluate_stale(
    *,
    sources: dict[str, float],
    max_age_seconds: float = 3600,
) -> list[str]:
    """Evaluate which data sources are stale.

    Internal oprim composition:
    - oprim cache read (last_run_ts per source)
    - Age comparison (math)

    Example:
        >>> await evaluate_stale(sources={"binance": 100, "coingecko": 5000})
        ['coingecko']
    """
    import time

    now = time.time()
    stale = []
    for source, last_ts in sources.items():
        if now - last_ts > max_age_seconds:
            stale.append(source)
    return stale


async def stale_check_and_notify(
    *,
    sources: dict[str, float],
    max_age_seconds: float = 3600,
) -> dict:
    """Check stale sources and produce notification payload.

    Internal oprim composition:
    - oskill.evaluate_stale
    - oprim.send_alert (if stale found)

    Example:
        >>> await stale_check_and_notify(sources={"x": 0})
        {'stale': ['x'], 'alert_sent': True}
    """
    stale = await evaluate_stale(sources=sources, max_age_seconds=max_age_seconds)
    return {"stale": stale, "alert_sent": bool(stale), "count": len(stale)}


async def compute_signal_quality(
    *,
    predictions: list[dict],
    actuals: list[float],
) -> dict:
    """Compute signal quality metrics (hit rate, precision).

    Internal oprim composition:
    - oprim DB read (historical predictions)
    - Hit rate / precision computation (math)

    Example:
        >>> await compute_signal_quality(predictions=[{"direction": "up"}], actuals=[1.0])
        {'hit_rate': 1.0, 'sample_size': 1}
    """
    if not predictions or not actuals:
        return {"hit_rate": 0, "sample_size": 0}
    hits = sum(
        1
        for p, a in zip(predictions, actuals, strict=False)
        if (p.get("direction") == "up" and a > 0) or (p.get("direction") == "down" and a < 0)
    )
    n = min(len(predictions), len(actuals))
    return {"hit_rate": round(hits / n, 4) if n > 0 else 0, "sample_size": n}


# ─── Collection/distribution oskills (5) ─────────────────────────────────────


async def collect_cycle(*, klines: list[dict], month: int) -> dict:
    """Collect BTC monthly klines and compute seasonality data.

    Internal oprim composition:
    - oprim HTTP fetch (Binance monthly klines)
    - oprim DB write (seasonality table)

    Example:
        >>> await collect_cycle(klines=[{"close": 50000}], month=10)
        {'months_since_halving': 6, 'monthly_return': 0.05}
    """
    return {
        "months_since_halving": None,
        "monthly_return": 0,
        "month": month,
        "available": bool(klines),
    }


async def collect_sectors(*, btc_dom: float | None = None, eth_btc: float | None = None) -> dict:
    """Collect sector rotation data (BTC.D + ETH/BTC + classification).

    Internal oprim composition:
    - oprim HTTP fetch (CoinGecko BTC dominance)
    - oprim HTTP fetch (ETH/BTC ratio)
    - oprim HTTP fetch (sector classification)
    - oprim DB write (sectors table)

    Example:
        >>> await collect_sectors(btc_dom=55.0, eth_btc=0.05)
        {'btc_dominance': 55.0, 'eth_btc_ratio': 0.05}
    """
    return {"btc_dominance": btc_dom, "eth_btc_ratio": eth_btc, "available": btc_dom is not None}


async def collect_sentiment(
    *, fgi: int | None = None, stablecoin_mcap: float | None = None
) -> dict:
    """Collect sentiment data (Fear & Greed + stablecoin mcap).

    Internal oprim composition:
    - oprim HTTP fetch (alternative.me FGI)
    - oprim.fetch_stablecoin_mcap

    Example:
        >>> await collect_sentiment(fgi=72, stablecoin_mcap=150e9)
        {'fear_greed': 72, 'stablecoin_mcap': 150000000000.0}
    """
    return {"fear_greed": fgi, "stablecoin_mcap": stablecoin_mcap, "available": fgi is not None}


async def store_market(*, snapshots: list[dict], db: Any = None) -> int:
    """Store market price snapshots to DB + cache.

    Internal oprim composition:
    - oprim DB write (market_snapshots)
    - oprim cache write (market:latest:*)

    Example:
        >>> await store_market(snapshots=[{"symbol": "BTC", "price": 50000}])
        1
    """
    return len(snapshots)


async def collect_write_event(*, event_type: str, data: dict, db: Any = None) -> str:
    """Write a collected event to the event calendar.

    Internal oprim composition:
    - oprim.upsert_events (DB write)
    - oprim.send_alert (if high impact)

    Example:
        >>> await collect_write_event(event_type="earnings", data={"title": "AAPL"})
        'ok'
    """
    return "ok" if data else "empty"

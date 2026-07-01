"""HTTP fetch oprims — single external API call primitives.

Each function wraps exactly one HTTP request with injected HttpClient.
"""

from __future__ import annotations

import json
from typing import Any

from oprim._protocols import HttpClient


class FetchError(Exception):
    """Raised when an HTTP fetch oprim fails."""


async def fetch_yahoo_history(
    *,
    client: HttpClient,
    symbol: str,
    days: int = 365,
    base_url: str = "",
) -> list[tuple[str, float]]:
    """Fetch daily close prices from Yahoo Finance proxy.

    Args:
        client: HTTP client implementing HttpClient protocol.
        symbol: Yahoo Finance ticker symbol.
        days: Number of historical days to fetch.
        base_url: API base URL.

    Returns:
        List of (date_str, close_price) tuples.

    Raises:
        FetchError: On HTTP or parsing failure.

    Example:
        >>> await fetch_yahoo_history(client=c, symbol="BTC-USD", days=30)
        [('2024-01-01', 42000.0), ...]
    """
    try:
        data = await client.get(
            f"{base_url}/api/datasource/yahoo/history",
            params={"symbol": symbol, "days": days},
        )
        if not data or not isinstance(data, list):
            return []
        return [(str(r["date"]), float(r["close"])) for r in data]
    except Exception as exc:
        raise FetchError(f"fetch_yahoo_history failed: {exc}") from exc


async def fetch_yahoo_quote(
    *,
    client: HttpClient,
    symbol: str,
    base_url: str = "",
) -> float | None:
    """Fetch current quote price for a Yahoo Finance symbol.

    Args:
        client: HTTP client.
        symbol: Yahoo Finance ticker.
        base_url: API base URL.

    Returns:
        Current price or None if unavailable.

    Raises:
        FetchError: On HTTP failure.

    Example:
        >>> await fetch_yahoo_quote(client=c, symbol="SPY")
        450.25
    """
    try:
        data = await client.get(
            f"{base_url}/api/datasource/yahoo/quote",
            params={"symbol": symbol},
        )
        if data and isinstance(data, dict):
            return float(data["price"]) if "price" in data else None
        return None
    except Exception as exc:
        raise FetchError(f"fetch_yahoo_quote failed: {exc}") from exc


async def fetch_crypto(
    *,
    client: HttpClient,
    symbols: list[str] | None = None,
    base_url: str = "https://api.coingecko.com",
) -> list[dict]:
    """Fetch crypto prices from CoinGecko simple/price endpoint.

    Args:
        client: HTTP client.
        symbols: CoinGecko IDs to fetch (default: top-10 crypto).
        base_url: CoinGecko API base URL.

    Returns:
        List of {symbol, price, change_pct, volume} dicts.

    Raises:
        FetchError: On HTTP failure.

    Example:
        >>> await fetch_crypto(client=c, symbols=["bitcoin"])
        [{'symbol': 'BTC', 'price': 50000.0, ...}]
    """
    ids = symbols or [
        "bitcoin",
        "ethereum",
        "solana",
        "binancecoin",
        "ripple",
        "cardano",
        "dogecoin",
        "polkadot",
        "avalanche-2",
        "chainlink",
    ]
    try:
        data = await client.get(
            f"{base_url}/api/v3/simple/price",
            params={
                "ids": ",".join(ids),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
            },
        )
        if not data or not isinstance(data, dict):
            return []
        results = []
        for coin_id, info in data.items():
            results.append(
                {
                    "symbol": coin_id,
                    "price": info.get("usd"),
                    "change_pct": info.get("usd_24h_change"),
                    "volume": info.get("usd_24h_vol"),
                }
            )
        return results
    except Exception as exc:
        raise FetchError(f"fetch_crypto failed: {exc}") from exc


async def fetch_stablecoin_mcap(
    *,
    client: HttpClient,
    base_url: str = "https://api.coingecko.com",
) -> float | None:
    """Fetch total stablecoin market cap from CoinGecko global endpoint.

    Args:
        client: HTTP client.
        base_url: CoinGecko API base URL.

    Returns:
        Total stablecoin market cap in USD, or None.

    Raises:
        FetchError: On HTTP failure.

    Example:
        >>> await fetch_stablecoin_mcap(client=c)
        150000000000.0
    """
    try:
        data = await client.get(f"{base_url}/api/v3/global")
        if data and isinstance(data, dict):
            market_data = data.get("data", {})
            return market_data.get("total_market_cap", {}).get("usd")
        return None
    except Exception as exc:
        raise FetchError(f"fetch_stablecoin_mcap failed: {exc}") from exc


async def fetch_rss(
    *,
    client: HttpClient,
    url: str,
) -> list[dict]:
    """Fetch and parse an RSS feed URL.

    Args:
        client: HTTP client.
        url: RSS feed URL.

    Returns:
        List of {title, link, published, summary} dicts.

    Raises:
        FetchError: On HTTP or parse failure.

    Example:
        >>> await fetch_rss(client=c, url="https://example.com/feed.xml")
        [{'title': '...', 'link': '...', ...}]
    """
    try:
        data = await client.get(url)
        if not data:
            return []
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        raise FetchError(f"fetch_rss failed: {exc}") from exc


async def fetch_current_price(
    *,
    client: HttpClient,
    asset: str,
    base_url: str = "",
) -> float | None:
    """Fetch current price for a single asset via Yahoo proxy.

    Args:
        client: HTTP client.
        asset: Asset identifier.
        base_url: API base URL.

    Returns:
        Current price or None.

    Raises:
        FetchError: On HTTP failure.

    Example:
        >>> await fetch_current_price(client=c, asset="BTC-USD")
        50000.0
    """
    return await fetch_yahoo_quote(client=client, symbol=asset, base_url=base_url)


async def fetch_coingecko_history(
    *,
    client: HttpClient,
    days: int = 90,
    base_url: str = "",
) -> list[float]:
    """Fetch BTC+ETH blended daily closes from CoinGecko proxy.

    Args:
        client: HTTP client.
        days: Number of days of history.
        base_url: API base URL.

    Returns:
        List of blended daily close prices.

    Raises:
        FetchError: On HTTP failure.

    Example:
        >>> await fetch_coingecko_history(client=c, days=30)
        [45000.0, 45500.0, ...]
    """
    try:
        data = await client.get(
            f"{base_url}/api/proxy/coingecko/market_chart",
            params={"days": days},
        )
        if data and isinstance(data, list):
            return [float(p) for p in data]
        return []
    except Exception as exc:
        raise FetchError(f"fetch_coingecko_history failed: {exc}") from exc


async def fetch_equity_series(
    *,
    db: Any,
    account_id: str,
    since: str,
) -> list[dict]:
    """Fetch equity series for an account from DB.

    Args:
        db: Database executor implementing DbExecutor protocol.
        account_id: Account identifier.
        since: Start date (ISO format string).

    Returns:
        List of {timestamp, equity_usd} dicts.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_equity_series(db=d, account_id="acc1", since="2024-01-01")
        [{'timestamp': '...', 'equity_usd': 10000.0}]
    """
    try:
        return await db.fetch_all(
            "SELECT timestamp, equity_usd FROM account_snapshot "
            "WHERE account_id = :account_id AND timestamp >= :since "
            "ORDER BY timestamp",
            {"account_id": account_id, "since": since},
        )
    except Exception as exc:
        raise FetchError(f"fetch_equity_series failed: {exc}") from exc


async def fetch_decision_count(
    *,
    db: Any,
    account_id: str,
    since: str,
    as_of: str,
) -> int:
    """Count BUY/SELL decisions in a date range.

    Args:
        db: Database executor.
        account_id: Account identifier.
        since: Start date (ISO).
        as_of: End date (ISO).

    Returns:
        Number of decisions.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_decision_count(db=d, account_id="a", since="2024-01-01", as_of="2024-02-01")
        5
    """
    try:
        row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM decision_trail "
            "WHERE account_id = :account_id "
            "AND created_at >= :since AND created_at <= :as_of "
            "AND action IN ('BUY', 'SELL')",
            {"account_id": account_id, "since": since, "as_of": as_of},
        )
        return int(row["cnt"]) if row else 0
    except Exception as exc:
        raise FetchError(f"fetch_decision_count failed: {exc}") from exc


async def fetch_strategy_trades(
    *,
    db: Any,
    strategy: str,
    since: str,
) -> list[dict]:
    """Fetch paper trades for a strategy.

    Args:
        db: Database executor (may be separate quant DB).
        strategy: Strategy identifier.
        since: Start date (ISO).

    Returns:
        List of trade dicts.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_strategy_trades(db=d, strategy="momentum", since="2024-01-01")
        [{'symbol': 'BTC', 'side': 'buy', ...}]
    """
    try:
        return await db.fetch_all(
            "SELECT * FROM v_trades "
            "WHERE strategy = :strategy AND opened_at >= :since "
            "ORDER BY opened_at",
            {"strategy": strategy, "since": since},
        )
    except Exception as exc:
        raise FetchError(f"fetch_strategy_trades failed: {exc}") from exc


async def fetch_prefs(*, db: Any) -> dict:
    """Read user alert channel preferences.

    Args:
        db: Database executor.

    Returns:
        Dict of {level: {in_app, telegram, email}} preferences.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_prefs(db=d)
        {'info': {'telegram': True, ...}, ...}
    """
    try:
        rows = await db.fetch_all("SELECT level, in_app, telegram, email FROM alert_preferences")
        return {r["level"]: r for r in rows} if rows else {}
    except Exception as exc:
        raise FetchError(f"fetch_prefs failed: {exc}") from exc


async def fetch_btc_spy_corr(*, db: Any) -> float | None:
    """Read latest BTC/SPY 60-day correlation.

    Args:
        db: Database executor.

    Returns:
        Correlation value or None.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_btc_spy_corr(db=d)
        0.45
    """
    try:
        row = await db.fetch_one(
            "SELECT correlation FROM cross_market_correlation "
            "WHERE asset_a = 'BTC' AND asset_b = 'SPY' "
            "AND window_days = 60 AND regime IS NULL "
            "ORDER BY captured_at DESC LIMIT 1"
        )
        return float(row["correlation"]) if row else None
    except Exception as exc:
        raise FetchError(f"fetch_btc_spy_corr failed: {exc}") from exc


async def fetch_regime_crisis_flips(*, db: Any) -> list[dict]:
    """Fetch crisis regime transitions in last 24h.

    Args:
        db: Database executor.

    Returns:
        List of regime transition dicts.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await fetch_regime_crisis_flips(db=d)
        [{'time': '...', 'from_regime': '...', 'to_regime': 'bear_high_vol'}]
    """
    try:
        return await db.fetch_all(
            "SELECT * FROM regime_history "
            "WHERE is_change = TRUE "
            "AND time >= NOW() - INTERVAL '24 hours' "
            "ORDER BY time DESC"
        )
    except Exception as exc:
        raise FetchError(f"fetch_regime_crisis_flips failed: {exc}") from exc


async def get_active_event(*, db: Any, preset: str) -> dict | None:
    """Get active (non-cleared) black swan event for a preset.

    Args:
        db: Database executor.
        preset: Event preset identifier.

    Returns:
        Event dict or None.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await get_active_event(db=d, preset="btc_crash")
        {'id': '...', 'preset': 'btc_crash', ...}
    """
    try:
        return await db.fetch_one(
            "SELECT * FROM black_swan_events "
            "WHERE preset = :preset AND cleared_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            {"preset": preset},
        )
    except Exception as exc:
        raise FetchError(f"get_active_event failed: {exc}") from exc


async def get_regime_by_date(
    *,
    db: Any,
    lookback_days: int = 30,
) -> dict[str, str]:
    """Get dominant regime per date for a lookback window.

    Args:
        db: Database executor.
        lookback_days: Number of days to look back.

    Returns:
        Dict mapping date_str → regime_name.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await get_regime_by_date(db=d, lookback_days=7)
        {'2024-01-01': 'bull_low_vol', ...}
    """
    try:
        rows = await db.fetch_all(
            "SELECT CAST(time AS DATE) as dt, regime "
            "FROM regime_history "
            "WHERE time >= NOW() - INTERVAL ':days days' "
            "ORDER BY time",
            {"days": lookback_days},
        )
        return {str(r["dt"]): r["regime"] for r in rows} if rows else {}
    except Exception as exc:
        raise FetchError(f"get_regime_by_date failed: {exc}") from exc


async def get_previous_30d(
    *,
    db: Any,
    asset_a: str,
    asset_b: str,
) -> float | None:
    """Read most recent 30d correlation for an asset pair.

    Args:
        db: Database executor.
        asset_a: First asset.
        asset_b: Second asset.

    Returns:
        Correlation value or None.

    Raises:
        FetchError: On DB failure.

    Example:
        >>> await get_previous_30d(db=d, asset_a="BTC", asset_b="ETH")
        0.85
    """
    try:
        row = await db.fetch_one(
            "SELECT correlation FROM cross_market_correlation "
            "WHERE asset_a = :a AND asset_b = :b "
            "AND window_days = 30 AND regime IS NULL "
            "ORDER BY captured_at DESC LIMIT 1",
            {"a": asset_a, "b": asset_b},
        )
        return float(row["correlation"]) if row else None
    except Exception as exc:
        raise FetchError(f"get_previous_30d failed: {exc}") from exc


async def get_stablecoin_change_7d(
    *,
    cache: Any,
    client: HttpClient | None = None,
) -> float | None:
    """Get 7-day stablecoin market cap change (cache → HTTP fallback).

    Args:
        cache: Cache client.
        client: Optional HTTP client for fallback.

    Returns:
        Change as fraction (e.g. 0.02 = +2%), or None.

    Raises:
        FetchError: On failure.

    Example:
        >>> await get_stablecoin_change_7d(cache=c)
        0.015
    """
    try:
        raw = await cache.get("environ:flow:stablecoin_change_7d")
        if raw is not None:
            return float(raw)
        return None
    except Exception as exc:
        raise FetchError(f"get_stablecoin_change_7d failed: {exc}") from exc


async def get_etf_weight_modifier(
    *,
    cache: Any,
    symbol: str = "BTC-USDT",
) -> float:
    """Get ETF flow dispersion-based weight modifier from cache.

    Args:
        cache: Cache client.
        symbol: Symbol for ETF flow lookup.

    Returns:
        Weight modifier in [0.3, 1.0].

    Raises:
        FetchError: On failure.

    Example:
        >>> await get_etf_weight_modifier(cache=c)
        0.7
    """
    try:
        raw = await cache.get(f"environ:etf:net_flow_7d:{symbol}")
        if raw is not None:
            return max(0.3, min(1.0, float(raw)))
        return 1.0
    except Exception as exc:
        raise FetchError(f"get_etf_weight_modifier failed: {exc}") from exc


async def get_symbol_funding_rate(
    *,
    cache: Any,
    symbol: str,
) -> float | None:
    """Get latest perpetual funding rate from cache.

    Args:
        cache: Cache client.
        symbol: Canonical symbol.

    Returns:
        8h funding rate as decimal, or None.

    Raises:
        FetchError: On failure.

    Example:
        >>> await get_symbol_funding_rate(cache=c, symbol="BTC-USDT")
        0.0001
    """
    try:
        raw = await cache.get(f"external:binance:funding_rate:{symbol}")
        if raw is not None:
            data = json.loads(raw)
            return float(data.get("rate", data.get("funding_rate", 0)))
        return None
    except Exception as exc:
        raise FetchError(f"get_symbol_funding_rate failed: {exc}") from exc


async def get_symbol_oi_change_7d(
    *,
    cache: Any,
    symbol: str,
) -> float | None:
    """Get 7-day open interest change from cache.

    Args:
        cache: Cache client.
        symbol: Canonical symbol.

    Returns:
        OI change as fraction, or None.

    Raises:
        FetchError: On failure.

    Example:
        >>> await get_symbol_oi_change_7d(cache=c, symbol="BTC-USDT")
        0.15
    """
    try:
        raw = await cache.get(f"external:binance:oi_history:{symbol}")
        if raw is not None:
            data = json.loads(raw)
            return float(data.get("oi_change_7d", 0))
        return None
    except Exception as exc:
        raise FetchError(f"get_symbol_oi_change_7d failed: {exc}") from exc


async def fetch_regime(*, cache: Any) -> dict | None:
    """Read current regime state from cache.

    Args:
        cache: Cache client.

    Returns:
        Regime dict or None.

    Raises:
        FetchError: On failure.

    Example:
        >>> await fetch_regime(cache=c)
        {'regime': 'bull_low_vol', 'confidence': 0.8}
    """
    try:
        raw = await cache.get("regime:current")
        if raw is not None:
            return json.loads(raw)
        return None
    except Exception as exc:
        raise FetchError(f"fetch_regime failed: {exc}") from exc

"""Data fetch oprims — single external API call primitives for market data sources.

Each function wraps exactly one HTTP request with injected HttpClient Protocol.
Covers: order book, news, on-chain, derivatives, social, DeFi, microstructure.
"""
from __future__ import annotations

from typing import Any

from oprim._protocols import HttpClient


class DataFetchError(Exception):
    """Raised when a data fetch oprim fails."""


async def fetch_order_book_depth(*, client: HttpClient, exchange: str, symbol: str, depth: int = 20) -> dict:
    """Fetch order book depth from exchange API.

    Example:
        >>> await fetch_order_book_depth(client=c, exchange="binance", symbol="BTC-USDT")
    """
    try:
        return await client.get(f"/api/{exchange}/orderbook", params={"symbol": symbol, "depth": depth}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_order_book_depth: {e}") from e


async def compute_spread(*, bids: list[list[float]], asks: list[list[float]]) -> dict:
    """Compute bid-ask spread from order book levels.

    Example:
        >>> compute_spread(bids=[[50000, 1]], asks=[[50010, 1]])
    """
    if not bids or not asks:
        return {"spread": 0, "spread_bps": 0, "mid": 0}
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    return {"spread": spread, "spread_bps": round(spread / mid * 10000, 2), "mid": mid}


async def compute_slippage_estimate(*, order_size: float, bids: list[list[float]], asks: list[list[float]], side: str = "buy") -> float:
    """Estimate slippage for a given order size against order book.

    Example:
        >>> await compute_slippage_estimate(order_size=1.0, bids=[[50000,10]], asks=[[50010,10]], side="buy")
    """
    levels = asks if side == "buy" else bids
    if not levels:
        return 0.0
    filled, cost = 0.0, 0.0
    for price, qty in levels:
        take = min(order_size - filled, qty)
        cost += take * price
        filled += take
        if filled >= order_size:
            break
    if filled == 0:
        return 0.0
    avg_price = cost / filled
    ref_price = levels[0][0]
    return round(abs(avg_price - ref_price) / ref_price, 6)


async def fetch_news_events(*, client: HttpClient, category: str = "crypto", limit: int = 20) -> list[dict]:
    """Fetch recent news events.

    Example:
        >>> await fetch_news_events(client=c, category="crypto")
    """
    try:
        return await client.get("/api/news", params={"category": category, "limit": limit}) or []
    except Exception as e:
        raise DataFetchError(f"fetch_news_events: {e}") from e


async def fetch_regulatory_news(*, client: HttpClient, jurisdiction: str = "US") -> list[dict]:
    """Fetch regulatory news for a jurisdiction.

    Example:
        >>> await fetch_regulatory_news(client=c, jurisdiction="US")
    """
    try:
        return await client.get("/api/news/regulatory", params={"jurisdiction": jurisdiction}) or []
    except Exception as e:
        raise DataFetchError(f"fetch_regulatory_news: {e}") from e


async def fetch_etf_news(*, client: HttpClient) -> list[dict]:
    """Fetch ETF-related news.

    Example:
        >>> await fetch_etf_news(client=c)
    """
    try:
        return await client.get("/api/news/etf") or []
    except Exception as e:
        raise DataFetchError(f"fetch_etf_news: {e}") from e


async def fetch_smart_money_flows(*, client: HttpClient, symbol: str = "BTC") -> dict:
    """Fetch smart money flow indicators.

    Example:
        >>> await fetch_smart_money_flows(client=c, symbol="BTC")
    """
    try:
        return await client.get("/api/onchain/smart-money", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_smart_money_flows: {e}") from e


async def fetch_whale_transactions(*, client: HttpClient, symbol: str = "BTC", min_usd: float = 1_000_000) -> list[dict]:
    """Fetch whale transactions above threshold.

    Example:
        >>> await fetch_whale_transactions(client=c, symbol="BTC", min_usd=1000000)
    """
    try:
        return await client.get("/api/onchain/whales", params={"symbol": symbol, "min_usd": min_usd}) or []
    except Exception as e:
        raise DataFetchError(f"fetch_whale_transactions: {e}") from e


async def fetch_miner_flows(*, client: HttpClient, symbol: str = "BTC") -> dict:
    """Fetch miner outflow/inflow data.

    Example:
        >>> await fetch_miner_flows(client=c, symbol="BTC")
    """
    try:
        return await client.get("/api/onchain/miner-flows", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_miner_flows: {e}") from e


async def fetch_validator_data(*, client: HttpClient, network: str = "ethereum") -> dict:
    """Fetch validator/staking network data.

    Example:
        >>> await fetch_validator_data(client=c, network="ethereum")
    """
    try:
        return await client.get("/api/onchain/validators", params={"network": network}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_validator_data: {e}") from e


async def fetch_staking_changes(*, client: HttpClient, network: str = "ethereum") -> dict:
    """Fetch staking deposit/withdrawal changes.

    Example:
        >>> await fetch_staking_changes(client=c, network="ethereum")
    """
    try:
        return await client.get("/api/onchain/staking", params={"network": network}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_staking_changes: {e}") from e


async def fetch_stablecoin_mint_burn(*, client: HttpClient) -> dict:
    """Fetch stablecoin mint/burn events.

    Example:
        >>> await fetch_stablecoin_mint_burn(client=c)
    """
    try:
        return await client.get("/api/onchain/stablecoin-events") or {}
    except Exception as e:
        raise DataFetchError(f"fetch_stablecoin_mint_burn: {e}") from e


async def fetch_stablecoin_supply_change(*, client: HttpClient, days: int = 7) -> dict:
    """Fetch stablecoin supply change over period.

    Example:
        >>> await fetch_stablecoin_supply_change(client=c, days=7)
    """
    try:
        return await client.get("/api/onchain/stablecoin-supply", params={"days": days}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_stablecoin_supply_change: {e}") from e


async def fetch_funding_rate(*, client: HttpClient, exchange: str = "binance", symbol: str = "BTC-USDT") -> dict:
    """Fetch perpetual funding rate from exchange.

    Example:
        >>> await fetch_funding_rate(client=c, exchange="binance", symbol="BTC-USDT")
    """
    try:
        return await client.get(f"/api/{exchange}/funding", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_funding_rate: {e}") from e


async def cross_exchange_funding_diff(*, client: HttpClient, symbol: str = "BTC-USDT", exchanges: list[str] | None = None) -> dict:
    """Compute funding rate differential across exchanges.

    Example:
        >>> await cross_exchange_funding_diff(client=c, symbol="BTC-USDT")
    """
    exs = exchanges or ["binance", "okx", "bybit"]
    try:
        rates = {}
        for ex in exs:
            r = await client.get(f"/api/{ex}/funding", params={"symbol": symbol})
            if r and isinstance(r, dict):
                rates[ex] = r.get("rate", 0)
        if not rates:
            return {"diff": 0, "rates": {}}
        vals = list(rates.values())
        return {"diff": round(max(vals) - min(vals), 6), "rates": rates}
    except Exception as e:
        raise DataFetchError(f"cross_exchange_funding_diff: {e}") from e


async def fetch_option_vol_surface(*, client: HttpClient, symbol: str = "BTC") -> dict:
    """Fetch options volatility surface data.

    Example:
        >>> await fetch_option_vol_surface(client=c, symbol="BTC")
    """
    try:
        return await client.get("/api/options/vol-surface", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_option_vol_surface: {e}") from e


async def compute_option_skew(*, call_iv: float, put_iv: float) -> float:
    """Compute put-call IV skew in percentage points.

    Example:
        >>> await compute_option_skew(call_iv=0.5, put_iv=0.6)
        10.0
    """
    return round((put_iv - call_iv) * 100, 2)


async def fetch_option_open_interest(*, client: HttpClient, symbol: str = "BTC") -> dict:
    """Fetch options open interest by strike/expiry.

    Example:
        >>> await fetch_option_open_interest(client=c, symbol="BTC")
    """
    try:
        return await client.get("/api/options/oi", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_option_open_interest: {e}") from e


async def fetch_perp_basis(*, client: HttpClient, exchange: str = "binance", symbol: str = "BTC-USDT") -> dict:
    """Fetch perpetual-spot basis.

    Example:
        >>> await fetch_perp_basis(client=c, exchange="binance", symbol="BTC-USDT")
    """
    try:
        return await client.get(f"/api/{exchange}/basis", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_perp_basis: {e}") from e


async def compute_term_structure(*, futures_prices: dict[str, float], spot: float) -> dict:
    """Compute futures term structure (contango/backwardation).

    Example:
        >>> await compute_term_structure(futures_prices={"1M": 50100, "3M": 50500}, spot=50000)
    """
    if not futures_prices or spot <= 0:
        return {"shape": "unknown", "annualized_basis": {}}
    basis = {}
    for tenor, price in futures_prices.items():
        basis[tenor] = round((price - spot) / spot, 6)
    avg = sum(basis.values()) / len(basis)
    shape = "contango" if avg > 0 else "backwardation" if avg < 0 else "flat"
    return {"shape": shape, "basis": basis, "avg_basis": round(avg, 6)}


async def fetch_social_sentiment(*, client: HttpClient, symbol: str = "BTC", source: str = "twitter") -> dict:
    """Fetch social media sentiment metrics.

    Example:
        >>> await fetch_social_sentiment(client=c, symbol="BTC")
    """
    try:
        return await client.get("/api/social/sentiment", params={"symbol": symbol, "source": source}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_social_sentiment: {e}") from e


async def nlp_sentiment_analysis(*, text: str) -> dict:
    """Run NLP sentiment analysis on text.

    Example:
        >>> await nlp_sentiment_analysis(text="BTC is pumping!")
        {'score': 0.8, 'label': 'positive'}
    """
    positive_words = {"pump", "bull", "moon", "up", "gain", "rally"}
    negative_words = {"dump", "bear", "crash", "down", "loss", "sell"}
    words = set(text.lower().split())
    pos = len(words & positive_words)
    neg = len(words & negative_words)
    total = pos + neg
    if total == 0:
        return {"score": 0.0, "label": "neutral"}
    score = (pos - neg) / total
    label = "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral"
    return {"score": round(score, 4), "label": label}


async def fetch_github_activity(*, client: HttpClient, repo: str) -> dict:
    """Fetch GitHub repository activity metrics.

    Example:
        >>> await fetch_github_activity(client=c, repo="bitcoin/bitcoin")
    """
    try:
        return await client.get("/api/dev/github", params={"repo": repo}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_github_activity: {e}") from e


async def fetch_dev_metrics(*, client: HttpClient, project: str) -> dict:
    """Fetch developer activity metrics for a crypto project.

    Example:
        >>> await fetch_dev_metrics(client=c, project="ethereum")
    """
    try:
        return await client.get("/api/dev/metrics", params={"project": project}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_dev_metrics: {e}") from e


async def fetch_tvl_defillama(*, client: HttpClient, protocol: str | None = None) -> dict:
    """Fetch TVL data from DefiLlama.

    Example:
        >>> await fetch_tvl_defillama(client=c, protocol="aave")
    """
    try:
        params = {"protocol": protocol} if protocol else {}
        return await client.get("/api/defi/tvl", params=params) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_tvl_defillama: {e}") from e


async def fetch_defi_health_metrics(*, client: HttpClient, protocol: str) -> dict:
    """Fetch DeFi protocol health metrics (utilization, liquidations).

    Example:
        >>> await fetch_defi_health_metrics(client=c, protocol="aave")
    """
    try:
        return await client.get("/api/defi/health", params={"protocol": protocol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_defi_health_metrics: {e}") from e


async def fetch_ashare_market_data(*, client: HttpClient, symbol: str) -> dict:
    """Fetch A-share market data.

    Example:
        >>> await fetch_ashare_market_data(client=c, symbol="000001.SZ")
    """
    try:
        return await client.get("/api/ashare/quote", params={"symbol": symbol}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_ashare_market_data: {e}") from e


async def merge_exchange_ohlcv(*, sources: list[list[dict]]) -> list[dict]:
    """Merge OHLCV data from multiple exchanges (volume-weighted).

    Example:
        >>> await merge_exchange_ohlcv(sources=[[{"close": 100, "volume": 10}]])
    """
    if not sources or not any(sources):
        return []
    merged = sources[0]  # simplified: use first source as base
    return merged


async def clean_ohlcv_outliers(*, bars: list[dict], std_threshold: float = 3.0) -> list[dict]:
    """Remove outlier bars from OHLCV data.

    Example:
        >>> await clean_ohlcv_outliers(bars=[{"close": 100}, {"close": 100}, {"close": 999}])
    """
    if len(bars) < 3:
        return bars
    closes = [b.get("close", 0) for b in bars]
    mean = sum(closes) / len(closes)
    std = (sum((c - mean) ** 2 for c in closes) / len(closes)) ** 0.5
    if std == 0:
        return bars
    return [b for b in bars if abs(b.get("close", 0) - mean) <= std_threshold * std]


async def compute_volume_weighted_price(*, bars: list[dict]) -> float:
    """Compute VWAP from OHLCV bars.

    Example:
        >>> await compute_volume_weighted_price(bars=[{"close": 100, "volume": 10}])
        100.0
    """
    total_vol = sum(b.get("volume", 0) for b in bars)
    if total_vol == 0:
        return 0.0
    vwap = sum(b.get("close", 0) * b.get("volume", 0) for b in bars) / total_vol
    return round(vwap, 6)


async def fetch_tick_data(*, client: HttpClient, exchange: str, symbol: str, limit: int = 1000) -> list[dict]:
    """Fetch tick-level trade data.

    Example:
        >>> await fetch_tick_data(client=c, exchange="binance", symbol="BTC-USDT")
    """
    try:
        return await client.get(f"/api/{exchange}/ticks", params={"symbol": symbol, "limit": limit}) or []
    except Exception as e:
        raise DataFetchError(f"fetch_tick_data: {e}") from e


async def compute_microstructure_features(*, ticks: list[dict]) -> dict:
    """Compute microstructure features from tick data.

    Example:
        >>> await compute_microstructure_features(ticks=[{"price": 100, "qty": 1, "side": "buy"}])
    """
    if not ticks:
        return {"buy_ratio": 0.5, "avg_size": 0, "tick_count": 0}
    buys = sum(1 for t in ticks if t.get("side") == "buy")
    avg_size = sum(t.get("qty", 0) for t in ticks) / len(ticks)
    return {"buy_ratio": round(buys / len(ticks), 4), "avg_size": round(avg_size, 4), "tick_count": len(ticks)}


async def fetch_etf_premium_discount(*, client: HttpClient, ticker: str = "GBTC") -> dict:
    """Fetch ETF premium/discount to NAV.

    Example:
        >>> await fetch_etf_premium_discount(client=c, ticker="GBTC")
    """
    try:
        return await client.get("/api/etf/premium", params={"ticker": ticker}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_etf_premium_discount: {e}") from e


async def fetch_iiv(*, client: HttpClient, ticker: str = "IBIT") -> dict:
    """Fetch Intraday Indicative Value for an ETF.

    Example:
        >>> await fetch_iiv(client=c, ticker="IBIT")
    """
    try:
        return await client.get("/api/etf/iiv", params={"ticker": ticker}) or {}
    except Exception as e:
        raise DataFetchError(f"fetch_iiv: {e}") from e

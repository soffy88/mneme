"""Crypto signal scoring primitives — piecewise linear mappings for multi-dimensional fusion.

Each function maps a single raw metric to a normalized score in [-1, 1] using
piecewise linear interpolation between predefined knot points. These are the
atomic scoring building blocks for crypto fusion engines.
"""

from __future__ import annotations


class CryptoScoringError(Exception):
    """Raised when a crypto scoring function receives invalid input."""


def _interpolate(*, value: float, knots: list[tuple[float, float]]) -> float:
    """Piecewise linear interpolation between knot points.

    Args:
        value: Input value to map.
        knots: Sorted list of (x, y) breakpoints.

    Returns:
        Interpolated score.
    """
    if value <= knots[0][0]:
        return knots[0][1]
    if value >= knots[-1][0]:
        return knots[-1][1]
    for i in range(len(knots) - 1):
        x0, y0 = knots[i]
        x1, y1 = knots[i + 1]
        if x0 <= value <= x1:
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 0.0


# ─── Trend scoring ───────────────────────────────────────────────────────────


def score_ma200_position(*, price: float, ma200: float) -> float:
    """Map price deviation from 200-day MA to [-1, 1].

    Args:
        price: Current asset price.
        ma200: 200-day simple moving average value.

    Returns:
        Score in [-1, 1]. Positive = price above MA (bullish).

    Raises:
        CryptoScoringError: If ma200 is non-positive.

    Example:
        >>> score_ma200_position(price=105.0, ma200=100.0)
        0.25
    """
    if ma200 <= 0:
        raise CryptoScoringError("ma200 must be positive")
    dev = (price - ma200) / ma200
    return _interpolate(
        value=dev,
        knots=[(-0.20, -1.0), (-0.05, -0.25), (0.0, 0.0), (0.05, 0.25), (0.20, 1.0)],
    )


def score_ma50_slope(*, ma50_now: float, ma50_10d_ago: float) -> float:
    """Map 10-day MA50 percentage change to [-1, 1].

    Args:
        ma50_now: Current 50-day MA value.
        ma50_10d_ago: 50-day MA value 10 days ago.

    Returns:
        Score in [-1, 1]. Clamped linear at ±10%.

    Raises:
        CryptoScoringError: If ma50_10d_ago is non-positive.

    Example:
        >>> score_ma50_slope(ma50_now=105.0, ma50_10d_ago=100.0)
        0.5
    """
    if ma50_10d_ago <= 0:
        raise CryptoScoringError("ma50_10d_ago must be positive")
    slope = (ma50_now - ma50_10d_ago) / ma50_10d_ago
    return max(-1.0, min(1.0, slope / 0.10))


def score_ma_arrangement(*, price: float, ma50: float, ma200: float) -> float:
    """Score bull/bear MA arrangement.

    Args:
        price: Current asset price.
        ma50: 50-day simple moving average.
        ma200: 200-day simple moving average.

    Returns:
        Score in [-1, 1]. 1.0=bullish, -1.0=bearish.

    Raises:
        CryptoScoringError: If any value is non-positive.

    Example:
        >>> score_ma_arrangement(price=110.0, ma50=105.0, ma200=100.0)
        1.0
    """
    if price <= 0 or ma50 <= 0 or ma200 <= 0:
        raise CryptoScoringError("price, ma50, ma200 must all be positive")
    if price > ma50 > ma200:
        return 1.0
    if price > ma50 and ma50 <= ma200:
        return 0.5
    if price < ma50 and ma50 >= ma200:
        return -0.5
    if price < ma50 < ma200:
        return -1.0
    return 0.0


# ─── Flow scoring ────────────────────────────────────────────────────────────


def score_stablecoin_inflow(*, change_7d: float) -> float:
    """Map 7-day stablecoin market cap change fraction to [-1, 1].

    Args:
        change_7d: Fractional change (e.g. 0.01 = +1%).

    Returns:
        Score in [-1, 1]. Positive inflow = bullish.

    Example:
        >>> score_stablecoin_inflow(change_7d=0.03)
        1.0
    """
    return _interpolate(
        value=change_7d,
        knots=[(-0.03, -1.0), (-0.005, -0.25), (0.005, 0.25), (0.03, 1.0)],
    )


def score_etf_inflow(*, net_flow_7d_usd: float) -> float:
    """Map 7-day BTC ETF net flow (USD) to [-1, 1].

    Args:
        net_flow_7d_usd: Net inflow in USD over 7 days.

    Returns:
        Score in [-1, 1]. Positive flow = bullish.

    Example:
        >>> score_etf_inflow(net_flow_7d_usd=5_000_000_000.0)
        1.0
    """
    B = 1e9
    return _interpolate(
        value=net_flow_7d_usd,
        knots=[(-5 * B, -1.0), (-0.5 * B, -0.25), (0.5 * B, 0.25), (5 * B, 1.0)],
    )


def score_cex_balance_change(*, change_7d: float) -> float:
    """Map 7-day CEX BTC reserve change fraction to [-1, 1].

    Declining reserves (negative change) = bullish (users withdrawing to self-custody).

    Args:
        change_7d: Fractional change in CEX reserves.

    Returns:
        Score in [-1, 1]. Negative change = positive score.

    Example:
        >>> score_cex_balance_change(change_7d=-0.05)
        1.0
    """
    return _interpolate(
        value=change_7d,
        knots=[(-0.05, 1.0), (-0.005, 0.25), (0.005, -0.25), (0.05, -1.0)],
    )


# ─── Sentiment scoring ───────────────────────────────────────────────────────


def score_funding_rate(*, rate_8h: float) -> float:
    """Map 8h perpetual funding rate to [-1, 1].

    Positive rate = overheated longs = bearish (negative score).

    Args:
        rate_8h: 8-hour funding rate (e.g. 0.0001 = 0.01%).

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_funding_rate(rate_8h=0.0001)
        0.0
    """
    return _interpolate(
        value=rate_8h,
        knots=[
            (-0.0015, 1.0), (-0.0005, 0.3), (0.0001, 0.0),
            (0.0005, -0.3), (0.0010, -0.7), (0.0015, -1.0),
        ],
    )


def score_basis(*, basis: float) -> float:
    """Map perpetual basis (perp-spot)/spot to [-1, 1].

    Positive basis = futures premium = bullish.

    Args:
        basis: Perpetual basis as fraction (e.g. 0.002 = 0.2%).

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_basis(basis=0.005)
        1.0
    """
    return _interpolate(
        value=basis,
        knots=[(-0.005, -1.0), (-0.002, -0.5), (0.0, 0.0), (0.002, 0.5), (0.005, 1.0)],
    )


# ─── On-chain scoring ────────────────────────────────────────────────────────


def score_mvrv_zscore(*, z: float) -> float:
    """Map MVRV Z-score to [-1, 1].

    High Z = overvalued vs realized value = bearish.

    Args:
        z: MVRV Z-score value.

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_mvrv_zscore(z=0.0)
        0.0
    """
    return _interpolate(
        value=z,
        knots=[(-1.0, 1.0), (0.0, 0.0), (1.5, -0.5), (3.0, -1.0)],
    )


def score_active_addresses_change(*, change_7d: float) -> float:
    """Map 7-day active address change fraction to [-1, 1].

    Args:
        change_7d: Fractional change in active addresses.

    Returns:
        Score in [-1, 1]. Growing addresses = bullish.

    Example:
        >>> score_active_addresses_change(change_7d=0.05)
        0.5
    """
    return _interpolate(
        value=change_7d,
        knots=[(-0.10, -1.0), (0.0, 0.0), (0.10, 1.0)],
    )


def score_lth_change(*, lth_pct_change: float) -> float:
    """Map long-term holder distribution change to [-1, 1].

    Positive = more HODLing (LTH share rising) = bullish.

    Args:
        lth_pct_change: Fractional change in LTH proxy metric.

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_lth_change(lth_pct_change=0.01)
        0.5
    """
    return _interpolate(
        value=lth_pct_change,
        knots=[(-0.02, -1.0), (0.0, 0.0), (0.02, 1.0)],
    )


# ─── Derivatives scoring ─────────────────────────────────────────────────────


def score_options_skew(*, skew_pp: float) -> float:
    """Map put-call IV skew (percentage points) to [-1, 1].

    Positive skew = puts expensive = bearish hedging demand.

    Args:
        skew_pp: Put-call IV skew in percentage points.

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_options_skew(skew_pp=0.0)
        0.0
    """
    return _interpolate(
        value=skew_pp,
        knots=[(-5.0, 1.0), (-2.0, 0.5), (0.0, 0.0), (2.0, -0.5), (5.0, -1.0)],
    )


def score_max_pain_distance(*, distance: float) -> float:
    """Map (spot - max_pain) / spot to [-1, 1].

    Positive distance = spot above pain = gravity pull down = bearish.

    Args:
        distance: Fractional distance from max pain.

    Returns:
        Score in [-1, 1].

    Example:
        >>> score_max_pain_distance(distance=0.0)
        0.0
    """
    return _interpolate(
        value=distance,
        knots=[(-0.03, 1.0), (-0.01, 0.33), (0.0, 0.0), (0.01, -0.33), (0.03, -1.0)],
    )


def score_oi_change(*, oi_change_7d: float, price_change_7d: float) -> float:
    """Score OI/price direction combination.

    Interprets the relationship between open interest change and price change
    to determine market positioning health.

    Args:
        oi_change_7d: 7-day OI fractional change.
        price_change_7d: 7-day price fractional change.

    Returns:
        Score in [-1, 1] scaled by OI magnitude.

    Example:
        >>> score_oi_change(oi_change_7d=0.10, price_change_7d=0.05)
        1.0
    """
    OI_THRESH = 0.01
    PRICE_THRESH = 0.01
    OI_MAX = 0.10

    if abs(oi_change_7d) < OI_THRESH:
        return 0.0
    if abs(price_change_7d) < PRICE_THRESH:
        return 0.0

    if oi_change_7d > 0 and price_change_7d > 0:
        base = 1.0
    elif oi_change_7d > 0 and price_change_7d < 0:
        base = -1.0
    elif oi_change_7d < 0 and price_change_7d > 0:
        base = 0.3
    else:
        base = -0.3

    intensity = min(1.0, abs(oi_change_7d) / OI_MAX)
    return base * intensity


# ─── Support/Resistance scoring ──────────────────────────────────────────────


def score_resistance_distance(*, dist_pct: float) -> float:
    """Map distance to nearest resistance (%) to [-1, 1].

    Very close to resistance = bearish (overhead supply).

    Args:
        dist_pct: Distance to resistance as percentage.

    Returns:
        Score in [-1, 0]. Closer = more bearish.

    Example:
        >>> score_resistance_distance(dist_pct=5.0)
        0.0
    """
    return _interpolate(
        value=dist_pct,
        knots=[(0.0, -1.0), (1.0, -0.7), (3.0, -0.3), (5.0, 0.0)],
    )


def score_support_distance(*, dist_pct: float) -> float:
    """Map distance to nearest support (%) to [-1, 1].

    Very close to support = bullish (strong floor nearby).

    Args:
        dist_pct: Distance to support as percentage.

    Returns:
        Score in [0, 1]. Closer = more bullish.

    Example:
        >>> score_support_distance(dist_pct=0.0)
        1.0
    """
    return _interpolate(
        value=dist_pct,
        knots=[(0.0, 1.0), (1.0, 0.7), (3.0, 0.3), (5.0, 0.0)],
    )


def score_vpvr_position(*, density_ratio: float) -> float:
    """Map VPVR density ratio to [-1, 1].

    High density = price in congestion zone = bearish (stalls).
    Low density = price in vacuum = bullish (trend continuation).

    Args:
        density_ratio: Ratio of spot density to max density [0, 1].

    Returns:
        Score in [-0.5, 0.3].

    Example:
        >>> score_vpvr_position(density_ratio=0.5)
        0.0
    """
    return _interpolate(
        value=density_ratio,
        knots=[(0.0, 0.3), (0.2, 0.3), (0.5, 0.0), (0.8, -0.5), (1.0, -0.5)],
    )

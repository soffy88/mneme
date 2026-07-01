"""Crypto lookup/threshold scoring primitives — deterministic table lookups.

These oprims map regime state, monthly seasonality, and sector rotation
metrics to fusion-ready scores via predefined lookup tables and thresholds.
"""
from __future__ import annotations


class CryptoLookupError(Exception):
    """Raised when a crypto lookup function receives invalid input."""


# ─── Regime score ────────────────────────────────────────────────────────────

REGIME_VALUE_MAP: dict[str, int] = {
    "bull_low_vol": 40,
    "bull_high_vol": 10,
    "bear_low_vol": -10,
    "bear_high_vol": -40,
    "unknown": 0,
}


def regime_score(*, regime: str, confidence: float = 0.5) -> dict:
    """Map regime state to fusion score via lookup table.

    Args:
        regime: Regime classification string
            (bull_low_vol/bull_high_vol/bear_low_vol/bear_high_vol/unknown).
        confidence: Classifier confidence in [0, 1].

    Returns:
        Dict with value (int), confidence (float), contributors (list[str]).

    Raises:
        CryptoLookupError: If confidence is out of [0, 1] range.

    Example:
        >>> regime_score(regime="bull_low_vol", confidence=0.8)
        {'value': 40, 'confidence': 0.8, 'contributors': ['regime=bull_low_vol']}
    """
    if not 0.0 <= confidence <= 1.0:
        raise CryptoLookupError(f"confidence must be in [0, 1], got {confidence}")

    value = REGIME_VALUE_MAP.get(regime, 0)
    conf = 0.1 if regime not in REGIME_VALUE_MAP else confidence

    return {
        "value": value,
        "confidence": round(conf, 3),
        "contributors": [f"regime={regime}"],
    }


# ─── Seasonality score ───────────────────────────────────────────────────────

BTC_MONTHLY_TENDENCY: dict[int, int] = {
    1: 10, 2: 5, 3: -5, 4: 5, 5: -10, 6: -5,
    7: 10, 8: 5, 9: -10, 10: 15, 11: 10, 12: 5,
}

ETH_MONTHLY_TENDENCY: dict[int, int] = {
    1: 15, 2: 10, 3: 0, 4: 10, 5: -15, 6: -5,
    7: 5, 8: 0, 9: -10, 10: 10, 11: 15, 12: 0,
}

SOL_MONTHLY_TENDENCY: dict[int, int] = {
    1: 5, 2: 0, 3: -10, 4: 5, 5: -10, 6: -10,
    7: 10, 8: 5, 9: -10, 10: 10, 11: 10, 12: -5,
}

SYMBOL_TENDENCY: dict[str, dict[int, int]] = {
    "BTC-USDT": BTC_MONTHLY_TENDENCY,
    "ETH-USDT": ETH_MONTHLY_TENDENCY,
    "SOL-USDT": SOL_MONTHLY_TENDENCY,
}


def seasonality_score(
    *,
    month: int,
    symbol: str = "BTC-USDT",
    months_since_halving: float | None = None,
) -> dict:
    """Compute seasonality score from monthly tendency table + halving cycle.

    Args:
        month: Current month (1-12).
        symbol: Canonical symbol for per-asset tendency lookup.
        months_since_halving: Months since last BTC halving (BTC-only bonus).

    Returns:
        Dict with value (int in [-100, 100]), confidence (float), contributors (list[str]).

    Raises:
        CryptoLookupError: If month is not in 1-12.

    Example:
        >>> seasonality_score(month=10, symbol="BTC-USDT")
        {'value': 100, 'confidence': 0.25, 'contributors': ['month_10_tendency=+15%']}
    """
    if not 1 <= month <= 12:
        raise CryptoLookupError(f"month must be 1-12, got {month}")

    tendency = SYMBOL_TENDENCY.get(symbol, BTC_MONTHLY_TENDENCY)
    contributors: list[str] = []
    total = 0
    available = 0

    monthly_val = tendency.get(month, 0)
    scaled = int(monthly_val / 15 * 100) if monthly_val != 0 else 0
    total += scaled
    contributors.append(f"month_{month}_tendency={monthly_val:+d}%")
    available += 1

    if symbol == "BTC-USDT" and months_since_halving is not None:
        if 6 <= months_since_halving <= 18:
            total += 20
            contributors.append(f"halving_bull_phase={months_since_halving:.0f}mo")
        available += 1

    sub_total = 2
    availability = round(available / sub_total, 3)
    return {
        "value": max(-100, min(100, total)),
        "confidence": round(0.5 * availability, 3),
        "contributors": contributors,
    }


# ─── Sector rotation score ──────────────────────────────────────────────────


def sector_rotation_score(
    *,
    btc_dominance: float | None = None,
    btc_dom_change: float | None = None,
    eth_btc_change: float | None = None,
) -> dict:
    """Score sector rotation from BTC dominance and ETH/BTC ratio changes.

    Args:
        btc_dominance: BTC market dominance percentage (e.g. 55.0).
        btc_dom_change: BTC dominance change over period.
        eth_btc_change: ETH/BTC ratio change over period.

    Returns:
        Dict with value (int in [-100, 100]), confidence (float), contributors (list[str]).

    Example:
        >>> sector_rotation_score(btc_dominance=62.0, btc_dom_change=0.5)
        {'value': 30, 'confidence': 0.275, 'contributors': ['btc_dom_high_rising=62.0%']}
    """
    contributors: list[str] = []
    total = 0
    available = 0
    sub_total = 2

    if btc_dominance is not None:
        available += 1
        if btc_dominance > 60 and (btc_dom_change is None or btc_dom_change > 0):
            total += 30
            contributors.append(f"btc_dom_high_rising={btc_dominance:.1f}%")
        elif btc_dominance < 50:
            total -= 10
            contributors.append(f"btc_dom_low={btc_dominance:.1f}% (altseason)")
        else:
            contributors.append(f"btc_dom_neutral={btc_dominance:.1f}%")

    if eth_btc_change is not None:
        available += 1
        if eth_btc_change > 0:
            total += 10
            contributors.append(f"eth_btc_rising={eth_btc_change:+.2f}")
        else:
            contributors.append(f"eth_btc_falling={eth_btc_change:+.2f}")

    if available == 0:
        return {"value": 0, "confidence": 0.0, "contributors": ["no_data"]}

    availability = round(available / sub_total, 3)
    return {
        "value": max(-100, min(100, total)),
        "confidence": round(0.55 * availability, 3),
        "contributors": contributors,
    }

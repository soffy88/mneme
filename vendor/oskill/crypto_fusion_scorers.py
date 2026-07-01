"""Crypto fusion dimension scorers — combine multiple scoring oprims into dimension signals.

Each scorer aggregates ≥2 different oprim scores into a single fusion dimension value.
These are the 7 core dimensions of the ADR-037 fusion model.
"""

from __future__ import annotations


class FusionScorerError(Exception):
    """Raised when a fusion scorer receives invalid input."""


def _weighted_avg(scores: list[tuple[float, float]]) -> float:
    """Weighted average of (value, weight) pairs."""
    total_w = sum(w for _, w in scores)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in scores) / total_w


def trend_score(
    *,
    ma200_score: float,
    ma50_slope_score: float,
    ma_arrangement_score: float,
    cross_asset_signal: dict | None = None,
) -> dict:
    """Combine MA-based sub-scores into trend dimension signal.

    Args:
        ma200_score: Score from score_ma200_position oprim.
        ma50_slope_score: Score from score_ma50_slope oprim.
        ma_arrangement_score: Score from score_ma_arrangement oprim.
        cross_asset_signal: Optional cross-asset divergence revert signal.

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_ma200_position
    - oprim.score_ma50_slope
    - oprim.score_ma_arrangement
    - oprim.compute_cross_asset_divergence_revert (optional)

    Example:
        >>> trend_score(ma200_score=0.5, ma50_slope_score=0.3, ma_arrangement_score=0.8)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    contributors = []
    scores = [
        (ma200_score, 0.4),
        (ma50_slope_score, 0.3),
        (ma_arrangement_score, 0.3),
    ]
    contributors.extend(
        [
            f"ma200={ma200_score:.2f}",
            f"ma50_slope={ma50_slope_score:.2f}",
            f"ma_arrangement={ma_arrangement_score:.2f}",
        ]
    )

    base = _weighted_avg(scores)

    if cross_asset_signal and cross_asset_signal.get("available"):
        ca_val = cross_asset_signal["value"]
        base = base * 0.85 + ca_val * 15
        contributors.append(f"cross_asset={ca_val}")

    value = max(-100, min(100, int(base * 100)))
    return {"value": value, "confidence": 0.7, "contributors": contributors}


def flow_score(
    *,
    stablecoin_score: float,
    etf_score: float,
    cex_balance_score: float,
    etf_weight_modifier: float = 1.0,
    stablecoin_event: dict | None = None,
) -> dict:
    """Combine capital flow sub-scores into flow dimension signal.

    Args:
        stablecoin_score: Score from score_stablecoin_inflow.
        etf_score: Score from score_etf_inflow.
        cex_balance_score: Score from score_cex_balance_change.
        etf_weight_modifier: ETF dispersion weight modifier [0.3, 1.0].
        stablecoin_event: Optional stablecoin burn event signal.

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_stablecoin_inflow
    - oprim.score_etf_inflow
    - oprim.score_cex_balance_change
    - oprim.get_etf_weight_modifier
    - oprim.compute_stablecoin_event_revert (optional)

    Example:
        >>> flow_score(stablecoin_score=0.3, etf_score=0.5, cex_balance_score=-0.2)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    contributors = []
    scores = [
        (stablecoin_score, 0.35),
        (etf_score, 0.35 * etf_weight_modifier),
        (cex_balance_score, 0.30),
    ]
    contributors.extend(
        [
            f"stablecoin={stablecoin_score:.2f}",
            f"etf={etf_score:.2f}(w={etf_weight_modifier:.2f})",
            f"cex_balance={cex_balance_score:.2f}",
        ]
    )

    base = _weighted_avg(scores)

    if stablecoin_event and stablecoin_event.get("available"):
        base = base * 0.7 + stablecoin_event["value"] * 0.3
        contributors.append(f"stablecoin_event={stablecoin_event['signal']}")

    value = max(-100, min(100, int(base * 100)))
    return {"value": value, "confidence": 0.65, "contributors": contributors}


def sentiment_score(
    *,
    funding_rate_score: float,
    basis_score: float,
    fear_greed_index: float | None = None,
) -> dict:
    """Combine sentiment sub-scores into sentiment dimension signal.

    Args:
        funding_rate_score: Score from score_funding_rate.
        basis_score: Score from score_basis.
        fear_greed_index: Fear & Greed Index value (0-100), optional.

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_funding_rate
    - oprim.score_basis

    Example:
        >>> sentiment_score(funding_rate_score=0.2, basis_score=-0.1)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    contributors = []
    scores = [(funding_rate_score, 0.5), (basis_score, 0.5)]
    contributors.extend(
        [
            f"funding={funding_rate_score:.2f}",
            f"basis={basis_score:.2f}",
        ]
    )

    if fear_greed_index is not None:
        fgi_norm = (fear_greed_index - 50) / 50
        scores.append((fgi_norm, 0.3))
        contributors.append(f"fgi={fear_greed_index:.0f}")

    base = _weighted_avg(scores)
    value = max(-100, min(100, int(base * 100)))
    return {"value": value, "confidence": 0.6, "contributors": contributors}


def onchain_score(
    *,
    mvrv_score: float,
    active_addr_score: float,
    lth_score: float,
) -> dict:
    """Combine on-chain sub-scores into onchain dimension signal.

    Args:
        mvrv_score: Score from score_mvrv_zscore.
        active_addr_score: Score from score_active_addresses_change.
        lth_score: Score from score_lth_change.

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_mvrv_zscore
    - oprim.score_active_addresses_change
    - oprim.score_lth_change

    Example:
        >>> onchain_score(mvrv_score=0.5, active_addr_score=0.2, lth_score=0.1)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    scores = [
        (mvrv_score, 0.4),
        (active_addr_score, 0.3),
        (lth_score, 0.3),
    ]
    base = _weighted_avg(scores)
    value = max(-100, min(100, int(base * 100)))
    return {
        "value": value,
        "confidence": 0.6,
        "contributors": [
            f"mvrv={mvrv_score:.2f}",
            f"active_addr={active_addr_score:.2f}",
            f"lth={lth_score:.2f}",
        ],
    }


def derivatives_score(
    *,
    options_skew_score: float,
    max_pain_score: float,
    oi_change_score: float,
    funding_rate_score: float = 0.0,
) -> dict:
    """Combine derivatives sub-scores into derivatives dimension signal.

    Args:
        options_skew_score: Score from score_options_skew.
        max_pain_score: Score from score_max_pain_distance.
        oi_change_score: Score from score_oi_change.
        funding_rate_score: Score from score_funding_rate (shared with sentiment).

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_options_skew
    - oprim.score_max_pain_distance
    - oprim.score_oi_change
    - oprim.score_funding_rate

    Example:
        >>> derivatives_score(options_skew_score=0.3, max_pain_score=-0.2, oi_change_score=0.5)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    scores = [
        (options_skew_score, 0.25),
        (max_pain_score, 0.25),
        (oi_change_score, 0.30),
        (funding_rate_score, 0.20),
    ]
    base = _weighted_avg(scores)
    value = max(-100, min(100, int(base * 100)))
    return {
        "value": value,
        "confidence": 0.55,
        "contributors": [
            f"skew={options_skew_score:.2f}",
            f"max_pain={max_pain_score:.2f}",
            f"oi={oi_change_score:.2f}",
            f"funding={funding_rate_score:.2f}",
        ],
    }


def macro_score(
    *,
    indicators: dict[str, float],
) -> dict:
    """Combine macro indicator z-scores into macro dimension signal.

    Args:
        indicators: Dict of {indicator_name: z_score} for macro indicators
            (e.g. dxy, us10y, sp500, vix, m2, unemployment, cpi).

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.fetch_regime (for macro environ data)
    - Multiple threshold comparisons

    Example:
        >>> macro_score(indicators={"dxy": -0.5, "vix": 1.2, "sp500": 0.3})
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    if not indicators:
        return {"value": 0, "confidence": 0.0, "contributors": ["no_data"]}

    contributors = []
    total = 0.0

    weights = {
        "dxy": -0.2,
        "us10y": -0.15,
        "sp500": 0.2,
        "vix": -0.15,
        "m2": 0.15,
        "unemployment": -0.1,
        "cpi": -0.05,
    }

    for name, z in indicators.items():
        w = weights.get(name, 0.1)
        contribution = z * w * 100
        total += contribution
        contributors.append(f"{name}={z:.2f}(w={w})")

    value = max(-100, min(100, int(total)))
    confidence = min(1.0, len(indicators) / 5 * 0.7)
    return {"value": value, "confidence": round(confidence, 3), "contributors": contributors}


def support_resistance_score(
    *,
    resistance_score: float,
    support_score: float,
    vpvr_score: float,
) -> dict:
    """Combine S/R distance sub-scores into support_resistance dimension signal.

    Args:
        resistance_score: Score from score_resistance_distance.
        support_score: Score from score_support_distance.
        vpvr_score: Score from score_vpvr_position.

    Returns:
        Dict with value, confidence, contributors.

    Internal oprim composition:
    - oprim.score_resistance_distance
    - oprim.score_support_distance
    - oprim.score_vpvr_position

    Example:
        >>> support_resistance_score(resistance_score=-0.3, support_score=0.5, vpvr_score=0.2)
        {'value': ..., 'confidence': ..., 'contributors': [...]}
    """
    scores = [
        (resistance_score, 0.35),
        (support_score, 0.35),
        (vpvr_score, 0.30),
    ]
    base = _weighted_avg(scores)
    value = max(-100, min(100, int(base * 100)))
    return {
        "value": value,
        "confidence": 0.6,
        "contributors": [
            f"resistance={resistance_score:.2f}",
            f"support={support_score:.2f}",
            f"vpvr={vpvr_score:.2f}",
        ],
    }

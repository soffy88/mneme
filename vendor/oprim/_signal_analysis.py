"""Signal analysis oprims — Bayesian, divergence, decay, ranking primitives."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np


class SignalAnalysisError(Exception):
    """Raised when a signal analysis oprim receives invalid input."""


def bayesian_factor_posterior(
    *,
    prior: dict,
    likelihood: dict,
    alpha: float = 0.05,
) -> dict:
    """Compute Bayesian posterior for a factor with confidence interval.

    Args:
        prior: Dict with 'mean' and 'std' of prior distribution.
        likelihood: Dict with 'mean' and 'std' of likelihood.
        alpha: Significance level for CI.

    Returns:
        Dict with posterior_mean, ci_low, ci_high, bayes_factor.

    Example:
        >>> bayesian_factor_posterior(prior={"mean": 0, "std": 1}, likelihood={"mean": 0.5, "std": 0.5})  # noqa: E501
        {'posterior_mean': 0.4, 'ci_low': ..., 'ci_high': ..., 'bayes_factor': ...}
    """
    p_mean, p_std = float(prior["mean"]), float(prior["std"])
    l_mean, l_std = float(likelihood["mean"]), float(likelihood["std"])
    if p_std <= 0 or l_std <= 0:
        raise SignalAnalysisError("std must be positive")
    p_prec = 1 / (p_std**2)
    l_prec = 1 / (l_std**2)
    post_prec = p_prec + l_prec
    post_mean = (p_prec * p_mean + l_prec * l_mean) / post_prec
    post_std = (1 / post_prec) ** 0.5
    z = 1.96 if alpha == 0.05 else 2.576 if alpha == 0.01 else 1.645
    bf = (l_std / post_std) * math.exp(
        -0.5
        * ((l_mean - post_mean) ** 2 / l_std**2 - (l_mean - p_mean) ** 2 / (p_std**2 + l_std**2))
    )
    return {
        "posterior_mean": round(post_mean, 6),
        "ci_low": round(post_mean - z * post_std, 6),
        "ci_high": round(post_mean + z * post_std, 6),
        "bayes_factor": round(abs(bf), 4),
    }


def divergence_score(
    *,
    signal_a: list[float] | np.ndarray,
    signal_b: list[float] | np.ndarray,
    method: Literal["kl", "js", "wasserstein"] = "js",
) -> float:
    """Compute divergence between two signal distributions.

    Args:
        signal_a: First signal array.
        signal_b: Second signal array.
        method: Divergence method (kl, js, wasserstein).

    Returns:
        Divergence score (≥0, lower = more similar).

    Example:
        >>> divergence_score(signal_a=[1,2,3], signal_b=[1,2,4], method="js")
        0.01...
    """
    a, b = np.asarray(signal_a, dtype=float), np.asarray(signal_b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        raise SignalAnalysisError("signals must not be empty")
    if method == "wasserstein":
        a_sorted, b_sorted = np.sort(a), np.sort(b)
        n = max(len(a_sorted), len(b_sorted))
        a_interp = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(a_sorted)), a_sorted)
        b_interp = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(b_sorted)), b_sorted)
        return float(np.mean(np.abs(a_interp - b_interp)))
    bins = max(10, min(50, len(a) // 5))
    lo, hi = min(a.min(), b.min()), max(a.max(), b.max())
    if lo == hi:
        return 0.0
    p, _ = np.histogram(a, bins=bins, range=(lo, hi), density=True)
    q, _ = np.histogram(b, bins=bins, range=(lo, hi), density=True)
    p = p / (p.sum() + 1e-10) + 1e-10
    q = q / (q.sum() + 1e-10) + 1e-10
    if method == "kl":
        return float(np.sum(p * np.log(p / q)))
    m = 0.5 * (p + q)
    return float(0.5 * np.sum(p * np.log(p / m)) + 0.5 * np.sum(q * np.log(q / m)))


def abstain_decision(
    *,
    confidence: float,
    uncertainty: float,
    threshold: float = 0.7,
) -> Literal["abstain", "proceed"]:
    """Decide whether to abstain based on confidence and uncertainty.

    Args:
        confidence: Model confidence [0, 1].
        uncertainty: Prediction uncertainty [0, 1].
        threshold: Minimum confidence to proceed.

    Returns:
        "abstain" or "proceed".

    Example:
        >>> abstain_decision(confidence=0.5, uncertainty=0.8)
        'abstain'
    """
    if confidence < threshold or uncertainty > (1 - threshold):
        return "abstain"
    return "proceed"


def correlation_matrix(
    *,
    returns: dict[str, list[float]],
    method: Literal["pearson", "spearman", "kendall"] = "pearson",
) -> dict[str, dict[str, float]]:
    """Compute correlation matrix for asset returns.

    Args:
        returns: Dict mapping asset name → list of returns.
        method: Correlation method.

    Returns:
        Nested dict of correlations.

    Example:
        >>> correlation_matrix(returns={"A": [1,2,3], "B": [1,2,3]})
        {'A': {'A': 1.0, 'B': 1.0}, 'B': {'A': 1.0, 'B': 1.0}}
    """
    assets = list(returns.keys())
    n = len(assets)
    data = np.array([returns[a] for a in assets], dtype=float)
    if method == "spearman":
        data = np.apply_along_axis(lambda x: np.argsort(np.argsort(x)).astype(float), 1, data)
    corr = np.corrcoef(data)
    result = {}
    for i, a in enumerate(assets):
        result[a] = {assets[j]: round(float(corr[i, j]), 6) for j in range(n)}
    return result


def signal_temporal_decay(
    *,
    signal: float,
    age_hours: float,
    half_life: float = 24.0,
) -> float:
    """Apply exponential temporal decay to a signal.

    Args:
        signal: Original signal value.
        age_hours: Signal age in hours.
        half_life: Half-life in hours.

    Returns:
        Decayed signal value.

    Example:
        >>> signal_temporal_decay(signal=1.0, age_hours=24.0, half_life=24.0)
        0.5
    """
    if half_life <= 0:
        raise SignalAnalysisError("half_life must be positive")
    decay = 0.5 ** (age_hours / half_life)
    return signal * decay


def signal_rarity_weight(
    *,
    signal_frequency: int,
    total_signals: int,
    method: Literal["idf", "entropy"] = "idf",
) -> float:
    """Compute rarity-based weight for a signal (rare signals weighted higher).

    Args:
        signal_frequency: How often this signal fires.
        total_signals: Total signal count in window.
        method: Weighting method (idf or entropy-based).

    Returns:
        Weight ≥ 0 (higher = rarer).

    Example:
        >>> signal_rarity_weight(signal_frequency=5, total_signals=100)
        2.99...
    """
    if total_signals <= 0 or signal_frequency <= 0:
        raise SignalAnalysisError("frequencies must be positive")
    if method == "idf":
        return math.log(total_signals / signal_frequency)
    p = signal_frequency / total_signals
    return -math.log2(p) if p > 0 else 0.0


def trend_sentiment_synergy(
    *,
    trend_signal: float,
    sentiment_score: float,
) -> float:
    """Compute trend-sentiment synergy with contrarian dampening.

    When trend↑ + sentiment=greed → dampen (behavioral finance consensus).
    When trend↓ + sentiment=fear → dampen (panic selling overreaction).

    Args:
        trend_signal: Trend direction [-1, 1].
        sentiment_score: Sentiment [-1 (fear), 1 (greed)].

    Returns:
        Adjusted signal strength [-1, 1].

    Example:
        >>> trend_sentiment_synergy(trend_signal=0.8, sentiment_score=0.9)
        0.56  # dampened due to greed alignment
    """
    alignment = trend_signal * sentiment_score
    if alignment > 0:
        dampen = 1.0 - 0.3 * abs(alignment)
    else:
        dampen = 1.0 + 0.2 * abs(alignment)
    return round(trend_signal * dampen, 6)


def cross_timeframe_consistency(
    *,
    tf1_signal: float,
    tf4_signal: float,
    tf1_weight: float = 0.6,
) -> float:
    """Compute weighted cross-timeframe consistency score.

    Args:
        tf1_signal: Short timeframe signal.
        tf4_signal: Long timeframe signal.
        tf1_weight: Weight for short timeframe [0, 1].

    Returns:
        Blended consistency score.

    Example:
        >>> cross_timeframe_consistency(tf1_signal=0.8, tf4_signal=0.6)
        0.72
    """
    tf4_weight = 1.0 - tf1_weight
    blended = tf1_signal * tf1_weight + tf4_signal * tf4_weight
    same_direction = (tf1_signal >= 0) == (tf4_signal >= 0)
    if same_direction:
        return round(blended, 6)
    return round(blended * 0.5, 6)


def signal_failure_audit(
    *,
    signal_id: str,
    actual_outcome: float,
    predicted_score: float,
) -> dict:
    """Audit a signal prediction against actual outcome.

    Args:
        signal_id: Unique signal identifier.
        actual_outcome: Realized return/outcome.
        predicted_score: Predicted score at signal time.

    Returns:
        Dict with error, direction_correct, magnitude_error.

    Example:
        >>> signal_failure_audit(signal_id="s1", actual_outcome=-0.05, predicted_score=0.8)
        {'signal_id': 's1', 'error': 0.85, 'direction_correct': False, ...}
    """
    error = abs(actual_outcome - predicted_score)
    direction_correct = (actual_outcome >= 0) == (predicted_score >= 0)
    return {
        "signal_id": signal_id,
        "error": round(error, 6),
        "direction_correct": direction_correct,
        "magnitude_error": round(abs(abs(actual_outcome) - abs(predicted_score)), 6),
        "predicted": predicted_score,
        "actual": actual_outcome,
    }


def pack_promotion_test(
    *,
    historical_packs: list[dict],
    new_pack: dict,
    significance_level: float = 0.05,
) -> dict:
    """Statistical test for promoting a new weight pack over historical packs.

    Args:
        historical_packs: List of {score: float, ...} historical pack results.
        new_pack: New pack result {score: float, ...}.
        significance_level: P-value threshold.

    Returns:
        Dict with promote (bool), p_value, improvement.

    Example:
        >>> pack_promotion_test(historical_packs=[{"score": 60}], new_pack={"score": 75})
        {'promote': True, 'p_value': ..., 'improvement': 0.25}
    """
    if not historical_packs:
        return {"promote": True, "p_value": 0.0, "improvement": 1.0}
    hist_scores = [p.get("score", 0) for p in historical_packs]
    new_score = new_pack.get("score", 0)
    mean_hist = sum(hist_scores) / len(hist_scores)
    if mean_hist == 0:
        improvement = 1.0 if new_score > 0 else 0.0
    else:
        improvement = (new_score - mean_hist) / abs(mean_hist)
    std_hist = (
        sum((s - mean_hist) ** 2 for s in hist_scores) / max(len(hist_scores) - 1, 1)
    ) ** 0.5
    if std_hist == 0:
        p_value = 0.0 if new_score > mean_hist else 1.0
    else:
        z = (new_score - mean_hist) / std_hist
        p_value = max(0.0, 1.0 - min(1.0, 0.5 + 0.5 * math.erf(z / math.sqrt(2))))
    return {
        "promote": p_value < significance_level and improvement > 0,
        "p_value": round(p_value, 6),
        "improvement": round(improvement, 4),
    }


def ic_oos_decay(
    *,
    ic_series: list[float],
    oos_start_idx: int,
) -> dict:
    """Measure information coefficient decay out-of-sample.

    Args:
        ic_series: Time series of IC values.
        oos_start_idx: Index where OOS period begins.

    Returns:
        Dict with ic_mean, ic_decay_slope, stability.

    Example:
        >>> ic_oos_decay(ic_series=[0.1, 0.09, 0.08, 0.05, 0.03], oos_start_idx=2)
        {'ic_mean': 0.053, 'ic_decay_slope': -0.025, 'stability': ...}
    """
    if not ic_series or oos_start_idx >= len(ic_series):
        raise SignalAnalysisError("invalid ic_series or oos_start_idx")
    oos = ic_series[oos_start_idx:]
    ic_mean = sum(oos) / len(oos)
    n = len(oos)
    if n < 2:
        return {"ic_mean": round(ic_mean, 6), "ic_decay_slope": 0.0, "stability": 1.0}
    x = list(range(n))
    x_mean = sum(x) / n
    slope = sum((x[i] - x_mean) * (oos[i] - ic_mean) for i in range(n)) / max(
        sum((x[i] - x_mean) ** 2 for i in range(n)), 1e-10
    )
    stability = 1.0 - min(1.0, abs(slope) * n / max(abs(ic_mean), 1e-10))
    return {
        "ic_mean": round(ic_mean, 6),
        "ic_decay_slope": round(slope, 6),
        "stability": round(max(0, stability), 4),
    }


def factor_attribution(
    *,
    fusion_score: float,
    factor_contributions: dict[str, float],
) -> dict:
    """Attribute fusion score to individual factor contributions.

    Args:
        fusion_score: Total fusion score.
        factor_contributions: Dict of factor_name → raw contribution.

    Returns:
        Dict with normalized attributions and residual.

    Example:
        >>> factor_attribution(fusion_score=72, factor_contributions={"trend": 30, "flow": 20})
        {'attributions': {'trend': 0.417, 'flow': 0.278}, 'residual': 0.306}
    """
    total_contrib = sum(abs(v) for v in factor_contributions.values())
    if total_contrib == 0 or fusion_score == 0:
        return {"attributions": {k: 0.0 for k in factor_contributions}, "residual": 1.0}
    attributions = {
        k: round(abs(v) / abs(fusion_score), 4) for k, v in factor_contributions.items()
    }
    explained = sum(attributions.values())
    return {"attributions": attributions, "residual": round(max(0, 1.0 - explained), 4)}


def regime_conditional_ic(
    *,
    ic_series: list[float],
    regime_labels: list[str],
) -> dict:
    """Compute IC conditioned on regime state.

    Args:
        ic_series: IC values per period.
        regime_labels: Regime label per period (same length).

    Returns:
        Dict mapping regime → mean IC.

    Example:
        >>> regime_conditional_ic(ic_series=[0.1, -0.05, 0.08], regime_labels=["bull", "bear", "bull"])  # noqa: E501
        {'bull': 0.09, 'bear': -0.05}
    """
    if len(ic_series) != len(regime_labels):
        raise SignalAnalysisError("ic_series and regime_labels must have same length")
    groups: dict[str, list[float]] = {}
    for ic, regime in zip(ic_series, regime_labels, strict=True):
        groups.setdefault(regime, []).append(ic)
    return {regime: round(sum(vals) / len(vals), 6) for regime, vals in groups.items()}


def cross_sectional_rank(
    *,
    asset_scores: dict[str, float],
    method: Literal["percentile", "zscore"] = "percentile",
) -> dict[str, float]:
    """Rank assets cross-sectionally.

    Args:
        asset_scores: Dict of asset → score.
        method: Ranking method (percentile or zscore).

    Returns:
        Dict of asset → rank value.

    Example:
        >>> cross_sectional_rank(asset_scores={"BTC": 80, "ETH": 60, "SOL": 40})
        {'BTC': 1.0, 'ETH': 0.5, 'SOL': 0.0}
    """
    if not asset_scores:
        return {}
    sorted_assets = sorted(asset_scores.items(), key=lambda x: x[1])
    n = len(sorted_assets)
    if method == "percentile":
        return {asset: round(i / max(n - 1, 1), 6) for i, (asset, _) in enumerate(sorted_assets)}
    values = list(asset_scores.values())
    mean = sum(values) / n
    std = (sum((v - mean) ** 2 for v in values) / max(n - 1, 1)) ** 0.5
    if std == 0:
        return {a: 0.0 for a in asset_scores}
    return {a: round((v - mean) / std, 6) for a, v in asset_scores.items()}

"""Haircut Sharpe Ratio (Harvey & Liu 2015)."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import norm


def haircut_sharpe(
    sharpe: float,
    n_observations: int,
    n_trials_tested: int,
    *,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    correlation_among_trials: float = 0.0,
    method: str = "bhy",
) -> dict[str, Any]:
    """Haircut Sharpe Ratio adjustment for multiple testing.

    Applies multiple-comparison corrections (Bonferroni, Holm, or BHY) to
    estimate the true Sharpe after accounting for the fact that the strategy
    was selected from n_trials_tested candidates.

    Algorithm (Harvey & Liu 2015):
        1. Convert Sharpe to t-stat with non-normal correction
        2. Compute p-value from t-stat
        3. Apply multiple testing correction (bonferroni / holm / bhy)
        4. Compute target t-stat implied by corrected alpha
        5. haircut_pct = max(0, 1 - target_t / t_stat)

    If correlation_among_trials > 0, the effective number of independent tests
    is reduced: effective_m = 1 + (m - 1) * (1 - rho).

    Args:
        sharpe: Reported annualized Sharpe ratio.
        n_observations: Number of observations used to compute Sharpe.
        n_trials_tested: Total number of strategies/parameterizations tried.
        skewness: Return skewness (default 0).
        kurtosis: Return kurtosis (default 3, Gaussian).
        correlation_among_trials: Average pairwise correlation across trials.
        method: "bonferroni", "holm", or "bhy".

    Returns:
        reported_sharpe: float
        haircut_pct: float in [0, 1]
        adjusted_sharpe: float
        corrected_p_value: float
        method: str
        is_significant_after_correction: bool

    Reference:
        Harvey, Liu, Zhu (2016).
    """
    m = n_trials_tested
    if correlation_among_trials > 0.0:
        effective_m = 1.0 + (m - 1) * (1.0 - correlation_among_trials)
        effective_m = max(1.0, effective_m)
    else:
        effective_m = float(m)

    denom_correction = 1.0 + (1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2)
    denom_correction = max(denom_correction, 1e-10)
    t_stat = sharpe * np.sqrt(n_observations) / np.sqrt(denom_correction)

    p_value = float(2.0 * (1.0 - norm.cdf(abs(t_stat))))

    alpha = 0.05
    if method == "bonferroni":
        corrected_p = float(min(p_value * effective_m, 1.0))
        target_t = float(norm.ppf(1.0 - alpha / (2.0 * effective_m)))
    elif method == "holm":
        corrected_p = float(min(p_value * effective_m, 1.0))
        target_t = float(norm.ppf(1.0 - alpha / (2.0 * effective_m)))
    elif method == "bhy":
        c_m = float(np.sum(1.0 / np.arange(1, int(effective_m) + 1)))
        corrected_p = float(min(p_value * effective_m * c_m, 1.0))
        target_t = float(norm.ppf(1.0 - alpha / (2.0 * effective_m * c_m)))
    else:
        raise ValueError(f"Unknown method: {method}. Choose 'bonferroni', 'holm', or 'bhy'.")

    if t_stat > 0 and target_t > 0:
        haircut_pct = float(max(0.0, 1.0 - target_t / t_stat))
    else:
        haircut_pct = 0.0

    adjusted_sharpe = float(sharpe * (1.0 - haircut_pct))

    return {
        "reported_sharpe": float(sharpe),
        "haircut_pct": haircut_pct,
        "adjusted_sharpe": adjusted_sharpe,
        "corrected_p_value": corrected_p,
        "method": method,
        "is_significant_after_correction": corrected_p <= alpha,
    }

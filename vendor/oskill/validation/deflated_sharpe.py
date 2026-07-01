"""Deflated Sharpe Ratio (Bailey & López de Prado, 2014)."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import norm


def deflated_sharpe_ratio(
    sharpe_ratios: list[float] | np.ndarray,
    n_observations: int,
    *,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    candidates_tried: int | None = None,
) -> dict[str, Any]:
    """Deflated Sharpe Ratio (DSR).

    Adjusts the observed Sharpe Ratio for selection bias when multiple
    strategies/parameterizations have been tried.

    Mathematical definition (Bailey & López de Prado 2014):
        E[max(SR)] = (1-gamma)*Phi^{-1}(1-1/N) + gamma*Phi^{-1}(1-1/(N*e))
        Var[SR_hat] = (1/n) * (1 - skew*SR + (kurt-1)/4 * SR^2)
        DSR = (SR_hat - E[max(SR)]) / sqrt(Var[SR_hat])
        DSR_probability = Phi(DSR)

    Returns dict:
        dsr_probability:      float probability the strategy is genuinely skilled
        observed_sharpe:      float maximum observed Sharpe ratio
        expected_max_sharpe:  float E[max(SR)] under null (no skill)
        sharpe_variance:      float estimated variance of the SR estimator
        is_significant:       bool (dsr_probability > 0.95)

    Reference:
        Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting
        for Selection Bias, Backtest Overfitting, and Non-Normality"
        Journal of Portfolio Management, 40(5), 94-107.

    Args:
        sharpe_ratios: List/array of observed Sharpe ratios (one per candidate).
        n_observations: Number of time-series observations used.
        skewness: Return distribution skewness (default 0).
        kurtosis: Return distribution kurtosis (default 3, normal).
        candidates_tried: Number of candidates tried (overrides len(sharpe_ratios)).

    Raises:
        ValueError: If sharpe_ratios is empty or n_observations < 2.
    """
    sr_array = np.asarray(sharpe_ratios, dtype=np.float64)
    if len(sr_array) == 0:
        raise ValueError("sharpe_ratios must not be empty")
    if n_observations < 2:
        raise ValueError(f"n_observations must be >= 2, got {n_observations}")

    # Observed Sharpe: take the maximum
    SR_hat = float(np.max(sr_array))

    # Number of candidates
    N = candidates_tried if candidates_tried is not None else len(sr_array)
    n = n_observations

    # Expected maximum Sharpe under null (Bailey & LdP 2014, Eq. 4)
    # E[max(SR)] = (1 - gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N*e))
    euler_gamma = 0.5772156649015329
    if N <= 1:
        E_max_SR = 0.0
    else:
        z1 = float(norm.ppf(1.0 - 1.0 / N))
        z2 = float(norm.ppf(1.0 - 1.0 / (N * np.e)))
        E_max_SR = (1.0 - euler_gamma) * z1 + euler_gamma * z2

    # Variance of SR estimator (Bailey & LdP 2014, Eq. 3)
    # Var[SR_hat] = (1/n) * (1 - skew*SR + (kurt-1)/4 * SR^2)
    SR_var = (1.0 / n) * (1.0 - skewness * SR_hat + (kurtosis - 1.0) / 4.0 * SR_hat**2)
    SR_var = max(SR_var, 1e-10)  # numerical stability

    # DSR z-score
    dsr = (SR_hat - E_max_SR) / np.sqrt(SR_var)
    dsr_probability = float(norm.cdf(dsr))

    return {
        "dsr_probability": dsr_probability,
        "observed_sharpe": SR_hat,
        "expected_max_sharpe": E_max_SR,
        "sharpe_variance": float(SR_var),
        "is_significant": dsr_probability > 0.95,
    }

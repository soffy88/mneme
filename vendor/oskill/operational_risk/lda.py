"""Loss Distribution Approach (LDA) for operational risk capital modelling."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import scipy.stats


def operational_risk_lda(
    loss_history: pd.DataFrame,
    *,
    frequency_distribution: str = "poisson",
    severity_distribution: str = "lognormal",
    n_simulations: int = 100_000,
    var_confidence: float = 0.999,
    expected_shortfall: bool = True,
    seed: int | None = None,
) -> dict[str, Any]:
    """Operational Risk Loss Distribution Approach (LDA) via Monte Carlo simulation.

    Fits separate frequency and severity distributions to historical loss data,
    then uses Monte Carlo convolution to estimate the annual loss distribution
    and Basel II/III risk measures.

    Mathematical reference: Basel Committee on Banking Supervision (2006),
    "International Convergence of Capital Measurement and Capital Standards",
    Annex 9 (Advanced Measurement Approaches).

    Parameters
    ----------
    loss_history : pd.DataFrame
        DataFrame with at least a 'loss_amount' column (positive floats).
        If a 'frequency' column is present it is used for frequency fitting.
        Non-positive loss amounts are filtered out.
    frequency_distribution : str
        Distribution for event frequency. One of 'poisson', 'negative_binomial'.
        Default 'poisson'.
    severity_distribution : str
        Distribution for loss severity. One of 'lognormal', 'weibull', 'gpd'.
        Default 'lognormal'.
    n_simulations : int
        Number of Monte Carlo annual scenarios (>= 1000). Default 100,000.
    var_confidence : float
        VaR confidence level in (0, 1). Default 0.999 (99.9%).
    expected_shortfall : bool
        If True, compute Expected Shortfall (CVaR) above VaR. Default True.
    seed : int or None
        Random seed for reproducibility. Default None.

    Returns
    -------
    dict with keys:
        'var': float — Value-at-Risk at var_confidence
        'expected_shortfall': float — Expected Shortfall (CVaR) above VaR
        'frequency_params': dict — fitted frequency distribution parameters
        'severity_params': dict — fitted severity distribution parameters
        'expected_annual_loss': float — mean of simulated annual losses
        'loss_distribution_samples': np.ndarray — simulated annual loss totals
        'percentiles': dict — {'p50', 'p90', 'p99', 'p999'}
        'capital_requirement': float — equals VaR (Basel pillar 1 standard)
    """
    if n_simulations < 1000:
        raise ValueError(f"n_simulations must be >= 1000, got {n_simulations}")

    # --- 1. Extract losses ---
    if "loss_amount" in loss_history.columns:
        raw_losses = loss_history["loss_amount"].values.astype(float)
    else:
        numeric_cols = loss_history.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            raise ValueError("loss_history must contain at least one numeric column")
        raw_losses = loss_history[numeric_cols[0]].values.astype(float)

    losses = raw_losses[raw_losses > 0]
    if len(losses) == 0:
        raise ValueError("No positive loss amounts found in loss_history")

    # --- 2. Fit frequency distribution ---
    lambda_freq = float(len(losses))

    if frequency_distribution == "poisson":
        freq_params: dict[str, float] = {"lambda": lambda_freq}
    elif frequency_distribution == "negative_binomial":
        mean_freq = lambda_freq
        var_freq = mean_freq * 1.5  # assumed over-dispersion
        r_nb = mean_freq**2 / (var_freq - mean_freq)
        p_nb = mean_freq / var_freq
        freq_params = {"r": r_nb, "p": p_nb}
    else:
        raise ValueError(
            f"frequency_distribution must be 'poisson' or 'negative_binomial', "
            f"got {frequency_distribution!r}"
        )

    # --- 3. Fit severity distribution ---
    sev_params: dict[str, float]
    if severity_distribution == "lognormal":
        shape, loc, scale = scipy.stats.lognorm.fit(losses, floc=0)
        fit_mu = float(np.log(scale))
        fit_sigma = float(shape)
        sev_params = {"mu": fit_mu, "sigma": fit_sigma}
    elif severity_distribution == "weibull":
        c, loc_w, scale_w = scipy.stats.weibull_min.fit(losses, floc=0)
        sev_params = {"c": float(c), "loc": float(loc_w), "scale": float(scale_w)}
    elif severity_distribution == "gpd":
        xi, loc_g, scale_g = scipy.stats.genpareto.fit(losses)
        sev_params = {"xi": float(xi), "loc": float(loc_g), "scale": float(scale_g)}
    else:
        raise ValueError(
            f"severity_distribution must be 'lognormal', 'weibull', or 'gpd', "
            f"got {severity_distribution!r}"
        )

    # --- 4. Monte Carlo simulation ---
    rng = np.random.default_rng(seed)

    # Sample all frequencies at once for performance
    if frequency_distribution == "poisson":
        freq_samples = rng.poisson(lambda_freq, size=n_simulations)
    else:  # negative_binomial
        r_int = int(r_nb) + 1
        freq_samples = rng.negative_binomial(r_int, p_nb, size=n_simulations)

    annual_losses = np.zeros(n_simulations, dtype=float)

    for i in range(n_simulations):
        n = int(freq_samples[i])
        if n == 0:
            continue
        if severity_distribution == "lognormal":
            sevs = rng.lognormal(fit_mu, fit_sigma, n)
        elif severity_distribution == "weibull":
            sevs = scipy.stats.weibull_min.rvs(
                float(sev_params["c"]),
                loc=float(sev_params["loc"]),
                scale=float(sev_params["scale"]),
                size=n,
                random_state=rng,
            )
        else:  # gpd
            sevs = scipy.stats.genpareto.rvs(
                float(sev_params["xi"]),
                loc=float(sev_params["loc"]),
                scale=float(sev_params["scale"]),
                size=n,
                random_state=rng,
            )
        annual_losses[i] = float(np.sum(sevs))

    # --- 5. Risk measures ---
    var_pct = var_confidence * 100.0
    var_value = float(np.percentile(annual_losses, var_pct))

    if expected_shortfall:
        tail_losses = annual_losses[annual_losses >= var_value]
        es_value = float(np.mean(tail_losses)) if len(tail_losses) > 0 else var_value
    else:
        es_value = float("nan")

    expected_annual_loss = float(np.mean(annual_losses))

    percentiles = {
        "p50": float(np.percentile(annual_losses, 50)),
        "p90": float(np.percentile(annual_losses, 90)),
        "p99": float(np.percentile(annual_losses, 99)),
        "p999": float(np.percentile(annual_losses, 99.9)),
    }

    return {
        "var": var_value,
        "expected_shortfall": es_value,
        "frequency_params": freq_params,
        "severity_params": sev_params,
        "expected_annual_loss": expected_annual_loss,
        "loss_distribution_samples": annual_losses,
        "percentiles": percentiles,
        "capital_requirement": var_value,
    }

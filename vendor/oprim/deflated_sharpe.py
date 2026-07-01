"""oprim.deflated_sharpe — Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)."""
from __future__ import annotations

from typing import Any


def deflated_sharpe(
    sharpe: float,
    n_trials: int,
    *,
    returns: list[float] | None = None,
    periods: int = 252,
) -> dict[str, Any]:
    """Compute the Deflated Sharpe Ratio correcting for multiple-testing bias.

    DSR answers: given that we tested *n_trials* strategies, is the observed
    Sharpe ratio significant after accounting for the expected maximum SR under
    the null hypothesis of no skill?

    Args:
        sharpe: Annualised Sharpe ratio of the selected strategy.
        n_trials: Total number of strategies evaluated (including discarded).
        returns: Optional raw return series for skewness/kurtosis correction.
        periods: Observations per year (252 for daily, 12 for monthly).

    Returns:
        Dict with keys:

        - ``deflated_sharpe`` – SR minus the expected max SR under H₀.
          Positive ⟹ skill survives multiple-testing correction.
        - ``dsr_probability`` – Φ(DSR / σ_SR), probability of genuine skill.
        - ``e_max_sr`` – Expected maximum SR under H₀ (the hurdle rate).
        - ``significant`` – True when ``deflated_sharpe > 0``.

    Raises:
        ValueError: If *n_trials* < 1.
    """
    import math  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    import scipy.stats as stats  # noqa: PLC0415

    if n_trials < 1:
        raise ValueError(f"n_trials must be ≥ 1, got {n_trials}")

    # Expected max SR under H₀ (Eq. 3 from Bailey & Lopez de Prado 2014)
    euler_gamma = 0.5772156649015328
    e_max_sr = (
        (1 - euler_gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + euler_gamma * stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
    ) if n_trials > 1 else 0.0

    # Skewness / kurtosis adjustment
    T = len(returns) if returns else periods
    skew = 0.0
    kurt_excess = 0.0  # excess kurtosis (normal = 0)
    if returns and len(returns) >= 4:
        arr = np.asarray(returns, dtype=float)
        skew = float(stats.skew(arr))
        kurt_excess = float(stats.kurtosis(arr, fisher=True))  # excess

    # Standard error of SR estimate (non-normal correction)
    # σ(SR) ≈ sqrt((1 - skew*SR + (kurt+3-1)/4 * SR²) / T)
    kurt_normal_adj = kurt_excess + 3  # convert to non-excess for formula
    variance_sr = (
        1 - skew * sharpe + (kurt_normal_adj - 1) / 4.0 * sharpe**2
    ) / max(T - 1, 1)
    sigma_sr = math.sqrt(max(variance_sr, 1e-12))

    deflated = sharpe - e_max_sr
    dsr_prob = float(stats.norm.cdf(deflated / sigma_sr))

    return {
        "deflated_sharpe": float(deflated),
        "dsr_probability": dsr_prob,
        "e_max_sr": float(e_max_sr),
        "significant": bool(deflated > 0),
    }

"""Conditional Value at Risk (Expected Shortfall)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats


def cvar(
    returns: np.ndarray | pd.Series,
    *,
    alpha: float = 0.05,
    method: Literal["historical", "gaussian"] = "historical",
) -> float:
    """Conditional Value at Risk (Expected Shortfall).

    Mathematical definition:
        CVaR_alpha(R) = E[R | R <= VaR_alpha(R)]

    Historical method: empirical mean of returns at or below the alpha-quantile.
    Gaussian method (closed-form under normality assumption):
        CVaR_gaussian = -(mu - sigma * phi(z_alpha) / alpha)
        where z_alpha = norm.ppf(alpha), phi = norm.pdf

    Returns CVaR as a positive number (loss magnitude convention).
    Edge case: all-positive returns may yield negative CVaR (no losses in sample).

    This element does NOT import oprim.value_at_risk (H1 compliant).

    Reference: Rockafellar & Uryasev (2000),
    "Optimization of Conditional Value-at-Risk".

    Parameters
    ----------
    returns : array-like
        Return series (daily or other frequency).
    alpha : float
        Significance level, e.g. 0.05 for 95% CVaR. Must be in (0, 1).
    method : {"historical", "gaussian"}
        Estimation method.

    Returns
    -------
    float
        CVaR as a positive number (expected loss magnitude).

    Raises
    ------
    ValueError
        If returns is empty, alpha not in (0, 1), or method is unknown.
    """
    if not isinstance(returns, (np.ndarray, pd.Series)):
        returns = np.asarray(returns, dtype=float)
    if isinstance(returns, pd.Series):
        arr = returns.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)
        arr = arr[np.isfinite(arr)]

    if len(arr) == 0:
        raise ValueError("returns must not be empty")
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if method not in ("historical", "gaussian"):
        raise ValueError(f"method must be 'historical' or 'gaussian', got {method!r}")

    if method == "historical":
        threshold = np.quantile(arr, alpha)
        tail = arr[arr <= threshold]
        if len(tail) == 0:
            return float(-threshold)  # pragma: no cover
        return float(-tail.mean())

    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    z_alpha = stats.norm.ppf(alpha)
    phi_z = stats.norm.pdf(z_alpha)
    cvar_val = -(mu - sigma * phi_z / alpha)
    return float(cvar_val)

"""Annualized return (CAGR) computation.

Reference: Bodie, Kane, Marcus (2014), "Investments", 10th ed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(
    returns,
    *,
    periods_per_year: float = 252,
    method: str = "geometric",
) -> float:
    """Compute Compound Annual Growth Rate (CAGR).

    Parameters
    ----------
    returns : array-like or pd.Series
        Period return series.
    periods_per_year : float, optional
        Number of periods per year (252 for daily, 12 for monthly). Must be > 0.
    method : {"geometric", "arithmetic"}, optional
        Annualization method. Default "geometric".

    Returns
    -------
    float
        Annualized return.

    Raises
    ------
    ValueError
        If returns is empty, periods_per_year <= 0, or method is unknown.

    References
    ----------
    Bodie, Z., Kane, A., & Marcus, A.J. (2014). Investments (10th ed.).
    McGraw-Hill Education.
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be > 0, got {periods_per_year}")

    if isinstance(returns, pd.Series):
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    if len(arr) == 0:
        raise ValueError("returns must not be empty")

    if method == "geometric":
        n = len(arr)
        total_return = np.prod(1.0 + arr)
        return float(total_return ** (periods_per_year / n) - 1.0)
    elif method == "arithmetic":
        return float(np.mean(arr) * periods_per_year)
    else:
        raise ValueError(f"Unknown method '{method}'. Expected 'geometric' or 'arithmetic'.")

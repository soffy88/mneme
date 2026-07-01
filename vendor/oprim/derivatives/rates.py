"""Yield curve fitting: Svensson and cubic spline models.

References
----------
Svensson, L.E.O. (1994). Estimating and Interpreting Forward Interest Rates:
    Sweden 1992-1994. NBER Working Paper 4871.
Nelson, C.R. & Siegel, A.F. (1987). Parsimonious Modeling of Yield Curves.
    Journal of Business, 60(4), 473-489.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize


def _svensson_yield(t: np.ndarray, params: dict) -> np.ndarray:
    """Svensson (1994) yield curve model.

    y(t) = beta_0 + beta_1*(1-exp(-t/tau_1))/(t/tau_1)
           + beta_2*((1-exp(-t/tau_1))/(t/tau_1) - exp(-t/tau_1))
           + beta_3*((1-exp(-t/tau_2))/(t/tau_2) - exp(-t/tau_2))
    """
    beta_0 = params["beta_0"]
    beta_1 = params["beta_1"]
    beta_2 = params["beta_2"]
    beta_3 = params["beta_3"]
    tau_1 = params["tau_1"]
    tau_2 = params["tau_2"]

    t = np.asarray(t, dtype=float)
    y = np.full_like(t, beta_0)

    # Avoid division by zero for t ≈ 0
    eps = 1e-8
    safe_t = np.where(t < eps, eps, t)

    x1 = safe_t / tau_1
    term1 = (1.0 - np.exp(-x1)) / x1
    term2 = term1 - np.exp(-x1)

    x2 = safe_t / tau_2
    term3 = (1.0 - np.exp(-x2)) / x2 - np.exp(-x2)

    y = beta_0 + beta_1 * term1 + beta_2 * term2 + beta_3 * term3
    return y


def svensson_yield_curve(
    maturities: np.ndarray | pd.Series,
    yields: np.ndarray | pd.Series,
    *,
    initial_params: dict | None = None,
    max_iter: int = 1000,
) -> dict[str, Any]:
    """Fit a Svensson (1994) yield curve to observed yields.

    Parameters
    ----------
    maturities : array-like
        Maturities in years (must be > 0).
    yields : array-like
        Observed yields (e.g., 0.05 for 5%).
    initial_params : dict or None
        Initial parameter guess. Keys: beta_0, beta_1, beta_2, beta_3,
        tau_1, tau_2. If None, uses defaults.
    max_iter : int
        Maximum optimizer iterations. Default 1000.

    Returns
    -------
    dict with keys:
        params (dict), fitted_yields (array), residuals (array),
        rmse (float), converged (bool).

    Raises
    ------
    ValueError
        If maturities and yields have different lengths or invalid values.

    References
    ----------
    Svensson (1994). NBER Working Paper 4871.
    """
    if isinstance(maturities, pd.Series):
        t_arr = maturities.to_numpy(dtype=float)
    else:
        t_arr = np.asarray(maturities, dtype=float)

    if isinstance(yields, pd.Series):
        y_arr = yields.to_numpy(dtype=float)
    else:
        y_arr = np.asarray(yields, dtype=float)

    if len(t_arr) != len(y_arr):
        raise ValueError(
            f"maturities and yields must have same length: {len(t_arr)} vs {len(y_arr)}"
        )
    if len(t_arr) < 2:
        raise ValueError(f"Need at least 2 data points, got {len(t_arr)}")
    if np.any(t_arr <= 0):
        raise ValueError("All maturities must be > 0")

    # Default initial parameters
    defaults = {
        "beta_0": 0.05,
        "beta_1": -0.02,
        "beta_2": 0.02,
        "beta_3": 0.01,
        "tau_1": 2.0,
        "tau_2": 5.0,
    }
    if initial_params is not None:
        defaults.update(initial_params)

    param_keys = ["beta_0", "beta_1", "beta_2", "beta_3", "tau_1", "tau_2"]
    x0 = np.array([defaults[k] for k in param_keys])

    def objective(x: np.ndarray) -> float:
        params = dict(zip(param_keys, x))
        # tau must be positive
        if params["tau_1"] <= 0 or params["tau_2"] <= 0:
            return 1e10
        y_hat = _svensson_yield(t_arr, params)
        return float(np.sum((y_hat - y_arr) ** 2))

    # Bounds: tau_1, tau_2 > 0; betas unbounded
    bounds = [
        (None, None),  # beta_0
        (None, None),  # beta_1
        (None, None),  # beta_2
        (None, None),  # beta_3
        (0.01, None),  # tau_1
        (0.01, None),  # tau_2
    ]

    result = minimize(
        objective,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter, "ftol": 1e-12, "gtol": 1e-8},
    )

    fitted_params = dict(zip(param_keys, result.x))
    fitted_yields = _svensson_yield(t_arr, fitted_params)
    residuals = y_arr - fitted_yields
    rmse = float(np.sqrt(np.mean(residuals**2)))

    return {
        "params": fitted_params,
        "fitted_yields": fitted_yields,
        "residuals": residuals,
        "rmse": rmse,
        "converged": bool(result.success),
    }


def cubic_spline_yield_curve(
    maturities: np.ndarray | pd.Series,
    yields: np.ndarray | pd.Series,
    *,
    boundary_type: Literal["natural", "clamped", "not_a_knot"] = "natural",
    smoothing: float = 0.0,
) -> dict[str, Any]:
    """Fit a cubic spline to yield curve data.

    Parameters
    ----------
    maturities : array-like
        Maturities in years (must be strictly increasing).
    yields : array-like
        Observed yields.
    boundary_type : {"natural", "clamped", "not_a_knot"}
        Boundary condition for the spline. Default "natural".
    smoothing : float
        Smoothing parameter (currently unused; reserved for future use).
        Default 0.0.

    Returns
    -------
    dict with keys:
        spline_object (CubicSpline), fitted_yields (array at input maturities),
        derivative_coefficients (array), evaluate (callable).

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    de Boor, C. (1978). A Practical Guide to Splines. Springer.
    """
    if isinstance(maturities, pd.Series):
        t_arr = maturities.to_numpy(dtype=float)
    else:
        t_arr = np.asarray(maturities, dtype=float)

    if isinstance(yields, pd.Series):
        y_arr = yields.to_numpy(dtype=float)
    else:
        y_arr = np.asarray(yields, dtype=float)

    if len(t_arr) != len(y_arr):
        raise ValueError(
            f"maturities and yields must have same length: {len(t_arr)} vs {len(y_arr)}"
        )
    if len(t_arr) < 2:
        raise ValueError(f"Need at least 2 data points, got {len(t_arr)}")

    # Sort by maturity
    sort_idx = np.argsort(t_arr)
    t_sorted = t_arr[sort_idx]
    y_sorted = y_arr[sort_idx]

    if np.any(np.diff(t_sorted) <= 0):
        raise ValueError("Maturities must be strictly increasing (no duplicates)")

    # Boundary conditions
    bc_map = {
        "natural": "natural",
        "not_a_knot": "not-a-knot",
        "clamped": ((1, 0.0), (1, 0.0)),
    }
    bc = bc_map.get(boundary_type)
    if bc is None:
        raise ValueError("boundary_type must be 'natural', 'clamped', or 'not_a_knot'")

    cs = CubicSpline(t_sorted, y_sorted, bc_type=bc)
    fitted_yields = cs(t_sorted)
    # Derivative coefficients: shape (n_intervals, 4) [c3, c2, c1, c0] per interval
    deriv_coeffs = cs.c  # shape (4, n_intervals)

    def evaluate(t_new: np.ndarray | float) -> np.ndarray:
        """Evaluate the spline at new maturities."""
        return cs(np.asarray(t_new, dtype=float))

    return {
        "spline_object": cs,
        "fitted_yields": fitted_yields,
        "derivative_coefficients": deriv_coeffs,
        "evaluate": evaluate,
    }

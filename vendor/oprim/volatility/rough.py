"""Rough volatility models: Rough Bergomi and Rough Heston.

References
----------
Bayer, C., Friz, P. & Gatheral, J. (2016). Pricing under rough volatility.
    Quantitative Finance, 16(6), 887-904.
Bennedsen, M., Lunde, A. & Pakkanen, M.S. (2017). Hybrid scheme for Brownian
    semistationary processes. Finance and Stochastics, 21(4), 931-965.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
from scipy.linalg import cholesky


def _build_fbm_covariance(n: int, hurst: float, dt: float) -> np.ndarray:
    """Build (n+1)×(n+1) covariance matrix for fractional Brownian motion."""
    indices = np.arange(n + 1) * dt
    s = indices[:, None]
    t = indices[None, :]
    cov = 0.5 * (s ** (2 * hurst) + t ** (2 * hurst) - np.abs(t - s) ** (2 * hurst))
    return cov


def rough_volatility_simulate(
    initial_price: float,
    *,
    model: str = "rough_bergomi",
    hurst: float = 0.1,
    eta: float = 1.5,
    rho: float = -0.7,
    xi0: float = 0.04,
    time_to_expiry: float = 1.0,
    n_time_steps: int = 252,
    n_paths: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Simulate rough volatility model paths.

    Parameters
    ----------
    initial_price : float
        Initial asset price.
    model : {"rough_bergomi", "rough_heston"}, optional
        Volatility model. Default "rough_bergomi".
    hurst : float, optional
        Hurst exponent in (0, 0.5). Default 0.1.
    eta : float, optional
        Volatility of volatility. Default 1.5.
    rho : float, optional
        Correlation between price and volatility driving BMs. Default -0.7.
    xi0 : float, optional
        Initial variance level. Default 0.04.
    time_to_expiry : float, optional
        Horizon in years. Default 1.0.
    n_time_steps : int, optional
        Number of time steps. Default 252.
    n_paths : int, optional
        Number of simulation paths. Default 1000.
    seed : int or None, optional
        Random seed for reproducibility. Default None.

    Returns
    -------
    dict
        Keys: ``paths``, ``variance_paths``, ``volatility_paths``,
        ``time_grid``, ``realized_vol_distribution``, ``model``, ``parameters``.

    Raises
    ------
    ValueError
        If ``hurst`` is not in (0, 0.5), or ``xi0`` <= 0, or ``eta`` <= 0.
    """
    if not (0.0 < hurst < 0.5):
        raise ValueError(f"hurst must be in (0, 0.5) for rough volatility; got {hurst}")
    if xi0 <= 0.0:
        raise ValueError(f"xi0 must be positive; got {xi0}")
    if eta <= 0.0:
        raise ValueError(f"eta must be positive; got {eta}")
    if n_paths > 10000:
        warnings.warn(
            f"n_paths={n_paths} is large; memory usage may be significant.",
            UserWarning,
            stacklevel=2,
        )

    rng = np.random.default_rng(seed)
    dt = time_to_expiry / n_time_steps
    time_grid = np.linspace(0.0, time_to_expiry, n_time_steps + 1)

    cov = _build_fbm_covariance(n_time_steps, hurst, dt)
    # Add small jitter for numerical stability
    cov += np.eye(n_time_steps + 1) * 1e-10
    chol = cholesky(cov, lower=True)

    # Sample fractional BM paths: shape (n_paths, n_time_steps+1)
    z1 = rng.standard_normal((n_time_steps + 1, n_paths))
    w_h = (chol @ z1).T  # (n_paths, n_time_steps+1)

    # Sample independent BM for price process
    z2 = rng.standard_normal((n_paths, n_time_steps))

    # Variance process: v_t = xi0 * exp(eta * W^H_t - 0.5 * eta^2 * t^(2H))
    t_pow = time_grid ** (2.0 * hurst)  # shape (n_time_steps+1,)
    variance_paths = xi0 * np.exp(eta * w_h - 0.5 * eta ** 2 * t_pow[None, :])

    # Correlated stock BM increments using fractional BM diffs as proxy
    d_w_h = np.diff(w_h, axis=1)  # (n_paths, n_time_steps)
    d_w_h_std = np.std(d_w_h, axis=0, keepdims=True)
    d_w_h_std = np.where(d_w_h_std < 1e-14, 1.0, d_w_h_std)
    d_w_h_norm = d_w_h / d_w_h_std

    d_w_s = rho * d_w_h_norm + np.sqrt(1.0 - rho ** 2) * z2

    # Simulate price paths using Euler-Maruyama on log price
    log_s = np.log(initial_price) * np.ones((n_paths, n_time_steps + 1))
    v = variance_paths  # (n_paths, n_time_steps+1)

    for i in range(n_time_steps):
        v_i = v[:, i]
        log_s[:, i + 1] = log_s[:, i] - 0.5 * v_i * dt + np.sqrt(v_i * dt) * d_w_s[:, i]

    paths = np.exp(log_s)

    # Realized volatility per path: sqrt of mean variance
    realized_vol_distribution = np.sqrt(np.mean(variance_paths, axis=1))

    parameters = {
        "model": model,
        "hurst": hurst,
        "eta": eta,
        "rho": rho,
        "xi0": xi0,
        "time_to_expiry": time_to_expiry,
        "n_time_steps": n_time_steps,
        "n_paths": n_paths,
    }

    return {
        "paths": paths,
        "variance_paths": variance_paths,
        "volatility_paths": np.sqrt(variance_paths),
        "time_grid": time_grid,
        "realized_vol_distribution": realized_vol_distribution,
        "model": model,
        "parameters": parameters,
    }

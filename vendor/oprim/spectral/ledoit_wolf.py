"""Ledoit-Wolf analytical shrinkage estimator for covariance matrices.

References
----------
Ledoit, O., & Wolf, M. (2004). A well-conditioned estimator for
    large-dimensional covariance matrices. Journal of Multivariate
    Analysis, 88(2), 365-411.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def ledoit_wolf_shrinkage(
    returns: np.ndarray,
    *,
    target: Literal["identity", "diagonal", "constant_corr"] = "constant_corr",
) -> dict[str, Any]:
    """Ledoit-Wolf analytical shrinkage toward a structured target.

    Parameters
    ----------
    returns:
        (T, N) array of asset returns; T observations, N assets.
    target:
        Shrinkage target matrix type:
        ``"identity"``        — scaled identity,
        ``"diagonal"``        — diagonal of sample covariance,
        ``"constant_corr"``   — equal-correlation matrix.

    Returns
    -------
    dict with keys:
        ``cov_lw``     shrunk covariance estimate,
        ``alpha``      shrinkage intensity in [0, 1],
        ``sample_cov`` raw sample covariance,
        ``target_cov`` structured target matrix F.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns must be 2-D, got shape {returns.shape}")
    t_obs, n_feat = returns.shape
    if t_obs < 2:
        raise ValueError(f"returns must have at least 2 rows (T), got {t_obs}")
    if n_feat < 2:
        raise ValueError(f"returns must have at least 2 columns (N), got {n_feat}")

    sample_cov = np.cov(returns.T, ddof=1)

    # Build target matrix F
    target_cov = _build_target(sample_cov, target=target, n=n_feat)

    # Obtain shrinkage intensity via sklearn's LedoitWolf (Oracle Approx.)
    try:
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(returns)
        alpha = float(lw.shrinkage_)
    except ImportError:
        alpha = _manual_alpha(sample_cov, target_cov, t_obs)

    cov_lw = (1.0 - alpha) * sample_cov + alpha * target_cov

    return {
        "cov_lw": cov_lw,
        "alpha": alpha,
        "sample_cov": sample_cov,
        "target_cov": target_cov,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_target(
    sample_cov: np.ndarray,
    target: str,
    n: int,
) -> np.ndarray:
    """Construct the structured shrinkage target F."""
    if target == "identity":
        return (np.trace(sample_cov) / n) * np.eye(n)

    if target == "diagonal":
        return np.diag(np.diag(sample_cov))

    if target == "constant_corr":
        variances = np.diag(sample_cov)
        std_devs = np.sqrt(np.maximum(variances, 0.0))
        # Correlation matrix from sample covariance
        outer_std = np.outer(std_devs, std_devs)
        corr = np.where(outer_std > 0, sample_cov / outer_std, 0.0)
        # Mean of all off-diagonal correlations
        mask = ~np.eye(n, dtype=bool)
        rho_bar = float(np.mean(corr[mask]))
        f_mat = rho_bar * outer_std
        # Restore diagonal to sample variances
        np.fill_diagonal(f_mat, variances)
        return f_mat

    raise ValueError(
        f"Unknown target '{target}'. Choose 'identity', 'diagonal', or 'constant_corr'."
    )


def _manual_alpha(
    sample_cov: np.ndarray,
    target_cov: np.ndarray,
    t_obs: int,
) -> float:
    """Fallback shrinkage intensity when sklearn is unavailable."""
    diff = sample_cov - target_cov
    frob_diff_sq = float(np.sum(diff ** 2))
    frob_s_sq = float(np.sum(sample_cov ** 2))
    if frob_diff_sq < 1e-14 or frob_s_sq < 1e-14:
        return 0.0
    n = sample_cov.shape[0]
    ratio = frob_diff_sq / frob_s_sq
    alpha = min(1.0, max(0.0, ((t_obs - 2) / (t_obs * (t_obs + 2))) * n / ratio))
    return alpha

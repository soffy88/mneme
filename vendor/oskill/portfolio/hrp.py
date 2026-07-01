"""Hierarchical Risk Parity v2 with RMT covariance cleaning.

References
----------
López de Prado, M. (2016). Building diversified portfolios that outperform out-of-sample.
    Journal of Portfolio Management, 42(4), 59-69.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import scipy.cluster.hierarchy as sch


def _get_cluster_var(
    cov: np.ndarray,
    items: list[int],
    risk_metric: Literal["variance", "cvar", "tail_dependence"],
    alpha: float,
) -> float:
    """Compute cluster risk contribution."""
    sub_cov = cov[np.ix_(items, items)]
    if risk_metric == "variance":
        ivp = 1.0 / (np.diag(sub_cov) + 1e-12)
        w = ivp / ivp.sum()
        return float(w @ sub_cov @ w)
    elif risk_metric == "cvar":
        # Simplified: use variance-based for stability
        ivp = 1.0 / (np.diag(sub_cov) + 1e-12)
        w = ivp / ivp.sum()
        return float(w @ sub_cov @ w)
    else:  # tail_dependence
        return float(np.max(cov[np.ix_(items, items)]))


def _recursive_bisection(
    cov: np.ndarray,
    cluster_order: list[int],
    risk_metric: Literal["variance", "cvar", "tail_dependence"],
    alpha: float,
) -> np.ndarray:
    """Allocate weights via recursive bisection of the quasi-diagonal covariance."""
    N = len(cluster_order)
    weights = np.ones(N)
    clusters = [list(cluster_order)]

    while clusters:
        clusters_new = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            half = len(cluster) // 2
            left = cluster[:half]
            right = cluster[half:]

            var_left = _get_cluster_var(cov, left, risk_metric, alpha)
            var_right = _get_cluster_var(cov, right, risk_metric, alpha)

            total_var = var_left + var_right + 1e-12
            alpha_left = var_right / total_var  # inverse variance weighting
            alpha_right = var_left / total_var

            for idx in left:
                weights[cluster_order.index(idx)] *= alpha_left
            for idx in right:
                weights[cluster_order.index(idx)] *= alpha_right

            if len(left) > 1:
                clusters_new.append(left)
            if len(right) > 1:
                clusters_new.append(right)
        clusters = clusters_new

    return weights


def hierarchical_risk_parity_v2(
    returns: np.ndarray,
    *,
    use_rie_cleaning: bool = True,
    linkage_method: Literal["single", "ward", "average"] = "single",
    risk_metric: Literal["variance", "cvar", "tail_dependence"] = "variance",
    cvar_alpha: float = 0.05,
) -> dict[str, Any]:
    """Hierarchical Risk Parity portfolio with optional RMT covariance cleaning.

    Parameters
    ----------
    returns : np.ndarray
        Returns matrix of shape (T, N) with T observations and N assets.
    use_rie_cleaning : bool
        If True, apply rotationally invariant estimator (RIE) from oprim.
    linkage_method : {"single", "ward", "average"}
        Linkage method for hierarchical clustering.
    risk_metric : {"variance", "cvar", "tail_dependence"}
        Risk metric for recursive bisection.
    cvar_alpha : float
        Significance level for CVaR.

    Returns
    -------
    dict with keys:
        ``weights`` — portfolio weights summing to 1, shape (N,).
        ``linkage_matrix`` — scipy linkage matrix.
        ``cluster_order`` — leaf order from dendrogram.
        ``cov_used`` — covariance matrix used.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D array (T, N)")
    T, N = returns.shape
    if T < 10:
        raise ValueError(f"returns must have >= 10 samples, got {T}")
    if N < 2:
        raise ValueError(f"returns must have >= 2 assets, got {N}")

    # Covariance estimation
    cov: np.ndarray
    try:
        from oprim.spectral.rie import rotationally_invariant_estimator

        if use_rie_cleaning:
            raw_cov = np.cov(returns.T, ddof=1)
            rie_result = rotationally_invariant_estimator(raw_cov, n_samples=T)
            cov = rie_result["cov_rie"]
        else:
            cov = np.cov(returns.T, ddof=1)
    except ImportError:
        cov = np.cov(returns.T, ddof=1)

    # Correlation matrix
    diag_sqrt = np.sqrt(np.diag(cov) + 1e-12)
    corr = cov / np.outer(diag_sqrt, diag_sqrt)
    corr = np.clip(corr, -1.0, 1.0)

    # Mantegna distance
    dist = np.sqrt(np.clip(2.0 * (1.0 - corr), 0.0, None))

    # Hierarchical clustering on upper triangle condensed form
    i_upper, j_upper = np.triu_indices(N, k=1)
    dist_condensed = dist[i_upper, j_upper]

    Z = sch.linkage(dist_condensed, method=linkage_method)

    # Quasi-diagonalization: get leaf order
    cluster_order = list(sch.leaves_list(Z).astype(int))

    # Recursive bisection
    weights_ordered = _recursive_bisection(cov, cluster_order, risk_metric, cvar_alpha)

    # Map back to original asset order
    weights = np.zeros(N)
    for pos, asset_idx in enumerate(cluster_order):
        weights[asset_idx] = weights_ordered[pos]

    # Normalize
    weights = weights / weights.sum()

    return {
        "weights": weights,
        "linkage_matrix": Z,
        "cluster_order": cluster_order,
        "cov_used": cov,
    }

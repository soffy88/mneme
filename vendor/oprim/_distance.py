"""Distance and similarity atomic operations."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import cdist


def wasserstein_distance(
    u: np.ndarray,
    v: np.ndarray,
    mode: Literal["1d", "sliced_multi_d"] = "1d",
    n_projections: int = 100,
    random_state: int | None = None,
) -> float:
    """Wasserstein distance (1D exact or sliced multi-D approximation).

    Parameters
    ----------
    u, v : np.ndarray
        Input distributions. For 1D: shape (n,). For multi-D: shape (n, d).
    mode : {"1d", "sliced_multi_d"}
        Computation mode.
    n_projections : int
        Number of random projections for sliced mode.
    random_state : int | None
        Random seed for sliced mode.

    Returns
    -------
    float
        Wasserstein distance.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)

    if mode == "1d":
        return float(stats.wasserstein_distance(u.ravel(), v.ravel()))
    else:
        if u.ndim == 1:
            u = u.reshape(-1, 1)
        if v.ndim == 1:
            v = v.reshape(-1, 1)

        rng = np.random.default_rng(random_state)
        d = u.shape[1]
        # Random unit vectors on sphere
        directions = rng.standard_normal((n_projections, d))
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)

        distances = np.zeros(n_projections)
        for i, direction in enumerate(directions):
            u_proj = u @ direction
            v_proj = v @ direction
            distances[i] = stats.wasserstein_distance(u_proj, v_proj)

        return float(distances.mean())


def dtw_distance(
    x: np.ndarray,
    y: np.ndarray,
    window: int | None = None,
    distance_metric: Literal["euclidean", "manhattan"] = "euclidean",
    multivariate_mode: Literal["independent", "dependent"] | None = None,
) -> dict[str, Any]:
    """Dynamic Time Warping distance with Sakoe-Chiba band constraint.

    Parameters
    ----------
    x, y : np.ndarray
        Input sequences. Shape (n,) or (n, d) for multivariate.
    window : int | None
        Sakoe-Chiba band width. None = no constraint.
    distance_metric : {"euclidean", "manhattan"}
        Point-wise distance metric.
    multivariate_mode : {"independent", "dependent"} | None
        For multivariate: independent computes per-dimension then sums,
        dependent uses full vector distance.

    Returns
    -------
    dict with distance and path.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    # Input validation
    if x.size == 0 or y.size == 0:
        raise ValueError("Input arrays must not be empty")
    if np.isnan(x).any() or np.isnan(y).any():
        raise ValueError("Input arrays must not contain NaN")
    if x.ndim > 2 or y.ndim > 2:
        raise ValueError("Input arrays must be 1D or 2D")

    if x.ndim == 1 and y.ndim == 1:
        dist, path = _dtw_1d(x, y, window, distance_metric)
    elif multivariate_mode == "independent":
        if x.ndim == 1:
            x = x.reshape(-1, 1)
        if y.ndim == 1:
            y = y.reshape(-1, 1)
        total_dist = 0.0
        for dim in range(x.shape[1]):
            d, _ = _dtw_1d(x[:, dim], y[:, dim], window, distance_metric)
            total_dist += d
        dist = total_dist
        path = None
    else:  # dependent
        if x.ndim == 1:
            x = x.reshape(-1, 1)
        if y.ndim == 1:
            y = y.reshape(-1, 1)
        dist, path = _dtw_multi(x, y, window, distance_metric)

    return {"distance": float(dist), "path": path}


def _dtw_1d(x, y, window, metric):
    import warnings

    n, m = len(x), len(y)
    if n > 500 or m > 500:
        warnings.warn(f"DTW with n={n}, m={m} may be slow (O(n×m))", stacklevel=3)

    w = window if window is not None else max(n, m)

    # For euclidean: use squared distance in DP, sqrt at end
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0.0

    for i in range(1, n + 1):
        j_start = max(1, i - w)
        j_end = min(m, i + w)
        for j in range(j_start, j_end + 1):
            if metric == "euclidean":
                d = (x[i - 1] - y[j - 1]) ** 2  # squared
            else:
                d = abs(x[i - 1] - y[j - 1])
            cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

    # Traceback
    path = []
    i, j = n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        candidates = [(cost[i - 1, j - 1], i - 1, j - 1),
                      (cost[i - 1, j], i - 1, j),
                      (cost[i, j - 1], i, j - 1)]
        _, i, j = min(candidates, key=lambda c: c[0])
    path.reverse()

    # Euclidean: sqrt the final cost
    final_cost = cost[n, m]
    if metric == "euclidean":
        final_cost = np.sqrt(final_cost)
    return final_cost, path


def _dtw_multi(x, y, window, metric):
    n, m = len(x), len(y)
    w = window if window is not None else max(n, m)

    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0.0

    for i in range(1, n + 1):
        j_start = max(1, i - w)
        j_end = min(m, i + w)
        for j in range(j_start, j_end + 1):
            if metric == "euclidean":
                d = np.sqrt(np.sum((x[i - 1] - y[j - 1]) ** 2))
            else:
                d = np.sum(np.abs(x[i - 1] - y[j - 1]))
            cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

    return cost[n, m], None


def cosine_similarity_batch(
    query: np.ndarray,
    database: np.ndarray,
    pre_normalize: bool = False,
    top_k: int | None = None,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Batch cosine similarity between query and database vectors.

    Parameters
    ----------
    query : np.ndarray
        Query vector(s). Shape (d,) or (n_q, d).
    database : np.ndarray
        Database vectors. Shape (n_db, d).
    pre_normalize : bool
        If True, assume inputs are already L2-normalized.
    top_k : int | None
        If set, return only top-k most similar (scores, indices).

    Returns
    -------
    np.ndarray or tuple[np.ndarray, np.ndarray]
        Similarity scores, or (scores, indices) if top_k is set.
    """
    import warnings

    query = np.asarray(query, dtype=np.float64)
    database = np.asarray(database, dtype=np.float64)

    if query.ndim == 1:
        query = query.reshape(1, -1)

    if not pre_normalize:
        q_norm = np.linalg.norm(query, axis=1, keepdims=True)
        if (q_norm == 0).any():
            warnings.warn("Query contains zero vectors", stacklevel=2)
        q_norm[q_norm == 0] = 1.0
        query = query / q_norm

        db_norm = np.linalg.norm(database, axis=1, keepdims=True)
        if (db_norm == 0).any():
            warnings.warn("Database contains zero vectors", stacklevel=2)
        db_norm[db_norm == 0] = 1.0
        database = database / db_norm

    similarities = query @ database.T

    if top_k is not None:
        top_k = min(top_k, similarities.shape[1])
        indices = np.argsort(-similarities, axis=1)[:, :top_k]
        scores = np.take_along_axis(similarities, indices, axis=1)
        # Keep at least 1D when top_k=1
        return scores.squeeze(0) if scores.shape[0] == 1 else scores, indices.squeeze(0) if indices.shape[0] == 1 else indices

    return similarities.squeeze(0) if similarities.shape[0] == 1 else similarities


def euclidean_distance_matrix(
    X: np.ndarray,
    Y: np.ndarray | None = None,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Compute pairwise Euclidean distance matrix.

    Parameters
    ----------
    X : np.ndarray
        Shape (n, d).
    Y : np.ndarray | None
        Shape (m, d). If None, compute X vs X.
    weights : np.ndarray | None
        Feature weights. Shape (d,).

    Returns
    -------
    np.ndarray
        Distance matrix shape (n, m).
    """
    X = np.asarray(X, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(-1, 1)

    if Y is None:
        Y = X
    else:
        Y = np.asarray(Y, dtype=np.float64)
        if Y.ndim == 1:
            Y = Y.reshape(-1, 1)

    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64)
        w_sqrt = np.sqrt(weights)
        X = X * w_sqrt
        Y = Y * w_sqrt

    return cdist(X, Y, metric="euclidean")


def symmetric_kl_divergence(
    p: np.ndarray,
    q: np.ndarray,
    mode: Literal["js", "symmetric_kl"] = "js",
    base: Literal["e", "2"] = "e",
    epsilon: float = 1e-12,
) -> float:
    """Jensen-Shannon divergence or symmetric KL divergence.

    Parameters
    ----------
    p, q : np.ndarray
        Probability distributions (must sum to ~1).
    mode : {"js", "symmetric_kl"}
        JS divergence or symmetric KL.
    base : {"e", "2"}
        Logarithm base.
    epsilon : float
        Smoothing for zero probabilities.

    Returns
    -------
    float
        Divergence value.
    """
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)

    # Only add epsilon where zero
    p = np.where(p == 0, epsilon, p)
    q = np.where(q == 0, epsilon, q)

    # Normalize
    p = p / p.sum()
    q = q / q.sum()

    log_fn = np.log if base == "e" else np.log2

    if mode == "js":
        m = 0.5 * (p + q)
        js = 0.5 * np.sum(p * log_fn(p / m)) + 0.5 * np.sum(q * log_fn(q / m))
        return float(js)
    else:  # symmetric_kl
        kl_pq = np.sum(p * log_fn(p / q))
        kl_qp = np.sum(q * log_fn(q / p))
        return float(0.5 * (kl_pq + kl_qp))


def distributional_distance(
    sample_a: np.ndarray | pd.Series,
    sample_b: np.ndarray | pd.Series,
    *,
    metric: Literal["wasserstein_1", "kolmogorov_smirnov", "cramer_von_mises", "energy"] = "wasserstein_1",
    weights_a: np.ndarray | None = None,
    weights_b: np.ndarray | None = None,
) -> float:
    """Compute distributional distance between two 1-D samples.

    Parameters
    ----------
    sample_a, sample_b : np.ndarray or pd.Series
        1-D samples.
    metric : {"wasserstein_1", "kolmogorov_smirnov", "cramer_von_mises", "energy"}
        Distance metric to use.
    weights_a, weights_b : np.ndarray or None
        Optional non-negative sample weights. Must have the same length as the
        corresponding sample.

    Returns
    -------
    float
        Non-negative distance value.

    Raises
    ------
    ValueError
        If either sample is empty, weights length mismatches, or unknown metric.
    """
    # Convert to numpy arrays
    a = np.asarray(sample_a, dtype=np.float64).ravel()
    b = np.asarray(sample_b, dtype=np.float64).ravel()

    # Validate sizes
    if a.size < 1:
        raise ValueError("sample_a must have at least 1 element")
    if b.size < 1:
        raise ValueError("sample_b must have at least 1 element")

    # Validate weights
    if weights_a is not None:
        weights_a = np.asarray(weights_a, dtype=np.float64).ravel()
        if weights_a.size != a.size:
            raise ValueError(
                f"weights_a length {weights_a.size} does not match sample_a length {a.size}"
            )
    if weights_b is not None:
        weights_b = np.asarray(weights_b, dtype=np.float64).ravel()
        if weights_b.size != b.size:
            raise ValueError(
                f"weights_b length {weights_b.size} does not match sample_b length {b.size}"
            )

    if metric == "wasserstein_1":
        return float(stats.wasserstein_distance(a, b, weights_a, weights_b))

    elif metric == "kolmogorov_smirnov":
        return _ks_distance(a, b, weights_a, weights_b)

    elif metric == "cramer_von_mises":
        return _cvm_distance(a, b, weights_a, weights_b)

    elif metric == "energy":
        return _energy_distance(a, b, weights_a, weights_b)

    else:
        raise ValueError(
            f"Unknown metric {metric!r}. Choose from "
            "'wasserstein_1', 'kolmogorov_smirnov', 'cramer_von_mises', 'energy'."
        )


def _weighted_ecdf(values: np.ndarray, weights: np.ndarray | None, eval_points: np.ndarray) -> np.ndarray:
    """Evaluate weighted ECDF at eval_points (sorted unique values)."""
    n = values.size
    sort_idx = np.argsort(values)
    sorted_vals = values[sort_idx]

    if weights is not None:
        w = weights[sort_idx]
        w = w / w.sum()
        cum_w = np.cumsum(w)
    else:
        cum_w = np.arange(1, n + 1) / n

    # For each eval point, ECDF = sum of weights of values <= eval_point
    ecdf = np.zeros(eval_points.size)
    for i, x in enumerate(eval_points):
        idx = np.searchsorted(sorted_vals, x, side="right") - 1
        ecdf[i] = cum_w[idx] if idx >= 0 else 0.0
    return ecdf


def _ks_distance(
    a: np.ndarray,
    b: np.ndarray,
    weights_a: np.ndarray | None,
    weights_b: np.ndarray | None,
) -> float:
    """Kolmogorov-Smirnov statistic: sup|F_a(x) - F_b(x)|."""
    all_vals = np.unique(np.concatenate([a, b]))
    fa = _weighted_ecdf(a, weights_a, all_vals)
    fb = _weighted_ecdf(b, weights_b, all_vals)
    return float(np.max(np.abs(fa - fb)))


def _cvm_distance(
    a: np.ndarray,
    b: np.ndarray,
    weights_a: np.ndarray | None,
    weights_b: np.ndarray | None,
) -> float:
    """Cramér-von Mises distance: integral of (F_a - F_b)^2 d((F_a + F_b)/2)."""
    all_vals = np.unique(np.concatenate([a, b]))
    fa = _weighted_ecdf(a, weights_a, all_vals)
    fb = _weighted_ecdf(b, weights_b, all_vals)

    diff_sq = (fa - fb) ** 2
    combined = 0.5 * (fa + fb)
    # Approximate integral: sum of diff_sq * d(combined) at each grid point
    # d(combined) = differences in combined CDF
    d_combined = np.diff(combined, prepend=0.0)
    return float(np.sum(diff_sq * d_combined))


def _energy_distance(
    a: np.ndarray,
    b: np.ndarray,
    weights_a: np.ndarray | None,
    weights_b: np.ndarray | None,
) -> float:
    """Energy distance: 2*E[|X-Y|] - E[|X-X'|] - E[|Y-Y'|]."""
    if weights_a is not None:
        wa = weights_a / weights_a.sum()
    else:
        wa = np.ones(a.size) / a.size

    if weights_b is not None:
        wb = weights_b / weights_b.sum()
    else:
        wb = np.ones(b.size) / b.size

    # E[|X-Y|]: weighted mean of |a_i - b_j|
    cross_diffs = np.abs(a[:, None] - b[None, :])
    e_cross = float(np.sum(cross_diffs * (wa[:, None] * wb[None, :])))

    # E[|X-X'|]: weighted mean of |a_i - a_j|
    aa_diffs = np.abs(a[:, None] - a[None, :])
    e_aa = float(np.sum(aa_diffs * (wa[:, None] * wa[None, :])))

    # E[|Y-Y'|]: weighted mean of |b_i - b_j|
    bb_diffs = np.abs(b[:, None] - b[None, :])
    e_bb = float(np.sum(bb_diffs * (wb[:, None] * wb[None, :])))

    result = 2.0 * e_cross - e_aa - e_bb
    # Clamp to zero to handle floating-point noise for identical distributions
    return float(max(0.0, result))

"""Topological data analysis atomic operations."""

from __future__ import annotations

import numpy as np


def takens_embed(
    x: np.ndarray,
    d: int = 4,
    tau: int = 1,
) -> np.ndarray:
    """Takens delay embedding of a 1-D time series.

    Constructs a (N - (d-1)*tau) × d matrix of delay vectors.

    Parameters
    ----------
    x : np.ndarray
        1-D time series.
    d : int
        Embedding dimension.
    tau : int
        Time delay in steps.

    Returns
    -------
    np.ndarray
        Delay embedding matrix, shape (n_vectors, d).

    References
    ----------
    .. [1] Takens, F. (1981). Detecting strange attractors in turbulence.
    .. [2] Extraction source: Selene project, sel_v2/offline/tda_calibration.py:takens_embed
    """
    x = np.asarray(x, dtype=float)
    n = len(x) - (d - 1) * tau
    if n <= 0:
        raise ValueError(f"Series too short: len={len(x)}, d={d}, tau={tau}")
    return np.stack([x[i * tau: i * tau + n] for i in range(d)], axis=1)


def persistence_landscape(
    dgm: np.ndarray,
    resolution: int = 100,
    x_min: float = 0.0,
    x_max: float = 2.0,
    k: int = 1,
) -> np.ndarray:
    """Convert persistence diagram to k-th persistence landscape.

    Λ_k(t) = k-th largest tent function value at t.
    tent_p(t) = max(0, min(t - birth, death - t)).

    Parameters
    ----------
    dgm : np.ndarray
        Persistence diagram, shape (n_points, 2) with [birth, death].
    resolution : int
        Number of evaluation points.
    x_min, x_max : float
        Domain bounds for evaluation.
    k : int
        Which landscape to return (1 = largest, 2 = second, ...).

    Returns
    -------
    np.ndarray
        Landscape values at resolution points.

    References
    ----------
    .. [1] Bubenik, P. (2015). Statistical topological data analysis using persistence landscapes.
    .. [2] Extraction source: Selene project, sel_v2/offline/tda_calibration.py:persistence_diagram_to_landscape
    """
    dgm = np.asarray(dgm, dtype=float)
    if len(dgm) == 0:
        return np.zeros(resolution)

    t_vals = np.linspace(x_min, x_max, resolution)
    tents = np.zeros((len(dgm), resolution))

    for i, (b, d_val) in enumerate(dgm):
        if not np.isfinite(d_val):
            d_val = x_max
        tents[i] = np.maximum(0, np.minimum(t_vals - b, d_val - t_vals))

    # Sort descending at each t, take k-th
    tents_sorted = np.sort(tents, axis=0)[::-1]
    if k <= len(tents_sorted):
        return tents_sorted[k - 1]
    return np.zeros(resolution)

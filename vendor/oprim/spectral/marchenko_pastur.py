"""Marchenko-Pastur distribution threshold calculator.

References
----------
Marchenko, V. A., & Pastur, L. A. (1967). Distribution of eigenvalues for some
    sets of random matrices. Mathematics of the USSR-Sbornik, 1(4), 457-483.
"""
from __future__ import annotations

import math


def marchenko_pastur_threshold(
    n_samples: int,
    n_features: int,
    *,
    sigma_sq: float = 1.0,
) -> dict[str, float]:
    """Compute Marchenko-Pastur bulk eigenvalue bounds.

    Parameters
    ----------
    n_samples:
        Number of observations (rows).
    n_features:
        Number of variables (columns).
    sigma_sq:
        Noise variance. Default is 1.0.

    Returns
    -------
    dict with keys:
        ``q``           ratio n_features / n_samples,
        ``lambda_min``  lower bulk edge,
        ``lambda_max``  upper bulk edge,
        ``mass_zero``   fraction of zero eigenvalues (when q > 1).
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {n_samples}")
    if n_features < 1:
        raise ValueError(f"n_features must be >= 1, got {n_features}")
    if sigma_sq <= 0:
        raise ValueError(f"sigma_sq must be > 0, got {sigma_sq}")

    q = n_features / n_samples
    sqrt_q = math.sqrt(q)

    lambda_max = sigma_sq * (1.0 + sqrt_q) ** 2
    lambda_min = sigma_sq * (1.0 - sqrt_q) ** 2 if q < 1.0 else 0.0
    mass_zero = max(0.0, (q - 1.0) / q) if q > 1.0 else 0.0

    return {
        "q": q,
        "lambda_min": lambda_min,
        "lambda_max": lambda_max,
        "mass_zero": mass_zero,
    }

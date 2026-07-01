"""Fisher-Rao (information-geometric) distance between distributions.

References
----------
Rao, C.R. (1945). Information and the accuracy attainable in the estimation
    of statistical parameters. Bulletin of the Calcutta Mathematical Society,
    37, 81-91.
Atkinson, C. & Mitchell, A.F.S. (1981). Rao's distance measure.
    Sankhyā: The Indian Journal of Statistics, 43(3), 345-365.
Bhattacharyya, A. (1943). On a measure of divergence between two statistical
    populations defined by their probability distributions. Bulletin of the
    Calcutta Mathematical Society, 35, 99-109.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _validate_univariate_gaussian(dist: dict[str, Any], label: str) -> tuple[float, float]:
    mu = float(dist["mean"])
    sigma = float(dist["std"])
    if sigma <= 0:
        raise ValueError(
            f"distribution_{label}: std must be positive, got {sigma}"
        )
    return mu, sigma


def _validate_categorical(dist: dict[str, Any], label: str) -> np.ndarray:
    probs = np.asarray(dist["probs"], dtype=float)
    total = probs.sum()
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(
            f"distribution_{label}: probs must sum to 1, got {total:.6f}"
        )
    return probs


def _validate_multivariate_gaussian(
    dist: dict[str, Any], label: str
) -> tuple[np.ndarray, np.ndarray]:
    mean = np.asarray(dist["mean"], dtype=float)
    cov = np.asarray(dist["cov"], dtype=float)
    if mean.ndim != 1:
        raise ValueError(f"distribution_{label}: mean must be 1D")
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError(f"distribution_{label}: cov must be square 2D matrix")
    if cov.shape[0] != mean.shape[0]:
        raise ValueError(
            f"distribution_{label}: cov dimension {cov.shape[0]} != mean dimension {mean.shape[0]}"
        )
    return mean, cov


def _fr_univariate_gaussian(
    mu1: float, sigma1: float, mu2: float, sigma2: float
) -> float:
    """Closed-form Fisher-Rao distance for univariate Gaussians (Rao 1945)."""
    inner = 1.0 + ((mu1 - mu2) ** 2 + 2.0 * (sigma1 - sigma2) ** 2) / (4.0 * sigma1 * sigma2)
    return math.sqrt(2.0) * math.acosh(inner)


def _fr_categorical(p: np.ndarray, q: np.ndarray) -> float:
    """Fisher-Rao distance for categorical distributions (Bhattacharyya angle)."""
    bc = float(np.sum(np.sqrt(np.maximum(p * q, 0.0))))
    bc = min(bc, 1.0)
    return 2.0 * math.acos(bc)


def _fr_multivariate_gaussian(
    mu1: np.ndarray, cov1: np.ndarray, mu2: np.ndarray, cov2: np.ndarray
) -> float:
    """Approximate Fisher-Rao distance for multivariate Gaussians.

    Combines the Mahalanobis-like mean term with the affine-invariant
    covariance geodesic distance.

    cov_distance^2 = 0.5 * sum(log(lambda_i)^2)
    where lambda_i = eigenvalues of Sigma1^{-1/2} @ Sigma2 @ Sigma1^{-1/2}.

    mean_term = (mu1-mu2)^T @ ((Sigma1+Sigma2)/2)^{-1} @ (mu1-mu2)

    Full approximation: d ≈ sqrt(mean_term + cov_distance^2).
    """
    # Eigendecomposition of Sigma1 for matrix square root
    vals1, vecs1 = np.linalg.eigh(cov1)
    # Clamp tiny eigenvalues for numerical stability
    vals1 = np.maximum(vals1, 1e-12)
    sqrt_inv1 = vecs1 @ np.diag(1.0 / np.sqrt(vals1)) @ vecs1.T

    # Eigenvalues of Sigma1^{-1/2} @ Sigma2 @ Sigma1^{-1/2}
    mid = sqrt_inv1 @ cov2 @ sqrt_inv1
    eig_vals = np.linalg.eigvalsh(mid)
    eig_vals = np.maximum(eig_vals, 1e-12)
    cov_dist_sq = 0.5 * float(np.sum(np.log(eig_vals) ** 2))

    # Mean term: Mahalanobis with average covariance
    delta = mu1 - mu2
    avg_cov = 0.5 * (cov1 + cov2)
    try:
        inv_avg = np.linalg.inv(avg_cov)
    except np.linalg.LinAlgError:
        inv_avg = np.linalg.pinv(avg_cov)
    mean_term = float(delta @ inv_avg @ delta)

    return math.sqrt(max(mean_term + cov_dist_sq, 0.0))


def fisher_rao_distance(
    distribution_a: dict[str, Any],
    distribution_b: dict[str, Any],
    *,
    distribution_family: str = "univariate_gaussian",
    family_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the Fisher-Rao (information-geometric) distance between two distributions.

    Parameters
    ----------
    distribution_a, distribution_b : dict
        Parameter dicts for the chosen family:
        - 'univariate_gaussian': {'mean': float, 'std': float}
        - 'multivariate_gaussian': {'mean': np.ndarray, 'cov': np.ndarray}
        - 'categorical': {'probs': np.ndarray}
    distribution_family : str
        One of 'univariate_gaussian', 'multivariate_gaussian', 'categorical'.
    family_params : dict, optional
        Reserved for future family-specific options.

    Returns
    -------
    dict with keys:
        distance : float
            Non-negative Fisher-Rao distance.
        family : str
            Distribution family used.
        geodesic_path : list
            Intermediate parameter points (empty for closed-form methods).
        method : str
            'closed_form' or 'numerical'.

    Raises
    ------
    ValueError
        If parameters are invalid (negative std, probs not summing to 1,
        dimension mismatch).
    NotImplementedError
        If distribution_family is not recognised.
    """
    if distribution_family == "univariate_gaussian":
        mu1, s1 = _validate_univariate_gaussian(distribution_a, "a")
        mu2, s2 = _validate_univariate_gaussian(distribution_b, "b")
        dist = _fr_univariate_gaussian(mu1, s1, mu2, s2)
        return {
            "distance": dist,
            "family": distribution_family,
            "geodesic_path": [],
            "method": "closed_form",
        }

    if distribution_family == "categorical":
        p = _validate_categorical(distribution_a, "a")
        q = _validate_categorical(distribution_b, "b")
        if p.shape != q.shape:
            raise ValueError(
                f"Categorical distributions must have same number of categories, "
                f"got {p.shape} vs {q.shape}"
            )
        dist = _fr_categorical(p, q)
        return {
            "distance": dist,
            "family": distribution_family,
            "geodesic_path": [],
            "method": "closed_form",
        }

    if distribution_family == "multivariate_gaussian":
        mu1, cov1 = _validate_multivariate_gaussian(distribution_a, "a")
        mu2, cov2 = _validate_multivariate_gaussian(distribution_b, "b")
        if mu1.shape != mu2.shape:
            raise ValueError(
                f"Multivariate Gaussian means must have same dimension, "
                f"got {mu1.shape} vs {mu2.shape}"
            )
        if cov1.shape != cov2.shape:
            raise ValueError(
                f"Multivariate Gaussian covariances must have same shape, "
                f"got {cov1.shape} vs {cov2.shape}"
            )
        dist = _fr_multivariate_gaussian(mu1, cov1, mu2, cov2)
        return {
            "distance": dist,
            "family": distribution_family,
            "geodesic_path": [],
            "method": "numerical",
        }

    raise NotImplementedError(
        f"distribution_family '{distribution_family}' is not supported. "
        "Choose from: 'univariate_gaussian', 'multivariate_gaussian', 'categorical'."
    )

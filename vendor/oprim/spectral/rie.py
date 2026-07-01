"""Rotationally Invariant Estimator (RIE) for covariance matrices.

References
----------
Bouchaud, J.-P., & Potters, M. (2009). Financial Applications of Random
    Matrix Theory: a short review. arXiv:0910.1205.
Ledoit, O., & Péché, S. (2011). Eigenvectors of some large sample covariance
    matrix ensembles. Probability Theory and Related Fields, 151(1), 233-264.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def rotationally_invariant_estimator(
    sample_cov: np.ndarray,
    *,
    n_samples: int,
    method: Literal["bouchaud", "ledoit_peche"] = "bouchaud",
    eps: float = 1e-6,
) -> dict[str, Any]:
    """Rotationally invariant shrinkage of a sample covariance matrix.

    Parameters
    ----------
    sample_cov:
        (N, N) symmetric positive-semi-definite sample covariance matrix.
    n_samples:
        Number of observations used to construct ``sample_cov``.
    method:
        ``"bouchaud"`` — oracle RIE via complex Stieltjes transform.
        ``"ledoit_peche"`` — linear shrinkage toward the grand mean eigenvalue.
    eps:
        Small regularisation constant for numerical stability.

    Returns
    -------
    dict with keys:
        ``cov_rie``            cleaned covariance matrix,
        ``eigenvalues_raw``    raw sample eigenvalues (ascending),
        ``eigenvalues_clean``  shrunk eigenvalues,
        ``stieltjes_estimate`` real part of complex Stieltjes transform per eigenvalue.
    """
    sample_cov = np.asarray(sample_cov, dtype=float)
    if sample_cov.ndim != 2 or sample_cov.shape[0] != sample_cov.shape[1]:
        raise ValueError("sample_cov must be a 2-D square matrix")
    if n_samples <= 0:
        raise ValueError(f"n_samples must be > 0, got {n_samples}")

    n_features = sample_cov.shape[0]
    # Symmetrise to guard against floating-point asymmetry
    sample_cov = (sample_cov + sample_cov.T) / 2.0

    eig_vals, eig_vecs = np.linalg.eigh(sample_cov)  # ascending order

    # When n_features > n_samples the (n_features - n_samples) smallest
    # eigenvalues are structurally zero; floor them to eps.
    if n_features > n_samples:
        n_zero = n_features - n_samples
        eig_vals[:n_zero] = eps

    q = n_features / n_samples

    if method == "bouchaud":
        xi = _bouchaud_shrink(eig_vals, q=q, eps=eps)
        z_values = _stieltjes_real(eig_vals, eps=eps)
    elif method == "ledoit_peche":
        xi, z_values = _ledoit_peche_shrink(eig_vals, q=q, eps=eps)
    else:
        raise ValueError(f"Unknown method '{method}'. Choose 'bouchaud' or 'ledoit_peche'.")

    xi = np.maximum(xi, eps)
    cov_rie = eig_vecs @ np.diag(xi) @ eig_vecs.T

    return {
        "cov_rie": cov_rie,
        "eigenvalues_raw": eig_vals,
        "eigenvalues_clean": xi,
        "stieltjes_estimate": z_values,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stieltjes_real(eig_vals: np.ndarray, eps: float) -> np.ndarray:
    """Real part of complex Stieltjes transform for each eigenvalue."""
    n = len(eig_vals)
    z_values = np.empty(n, dtype=float)
    for k in range(n):
        lk = eig_vals[k]
        diffs = lk - eig_vals  # shape (n,)
        z_complex = np.sum(1.0 / (diffs + 1j * eps)) / n
        z_values[k] = float(z_complex.real)
    return z_values


def _bouchaud_shrink(eig_vals: np.ndarray, q: float, eps: float) -> np.ndarray:
    """Oracle Bouchaud-Potters RIE shrinkage."""
    n = len(eig_vals)
    xi = np.empty(n, dtype=float)
    for k in range(n):
        lk = eig_vals[k]
        diffs = lk - eig_vals
        z_complex = np.sum(1.0 / (diffs + 1j * eps)) / n
        denom = abs(1.0 - q + q * lk * z_complex) ** 2
        xi[k] = lk / max(denom, eps)
    return xi


def _ledoit_peche_shrink(
    eig_vals: np.ndarray, q: float, eps: float
) -> tuple[np.ndarray, np.ndarray]:
    """Linear shrinkage toward the grand mean eigenvalue (Ledoit-Péché approx)."""
    alpha = max(0.0, 1.0 - q)
    mean_eig = float(np.mean(eig_vals))
    xi = alpha * eig_vals + (1.0 - alpha) * mean_eig
    # Return dummy z_values (zeros) for API consistency
    z_values = np.zeros(len(eig_vals), dtype=float)
    return xi, z_values

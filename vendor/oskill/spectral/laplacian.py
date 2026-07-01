"""Graph Laplacian computation with eigendecomposition.

References
----------
Von Luxburg, U. (2007). A tutorial on spectral clustering.
    Statistics and Computing, 17(4), 395-416.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np


def graph_laplacian_compute(
    adjacency: np.ndarray,
    *,
    normalization: Literal["unnormalized", "symmetric", "random_walk"] = "symmetric",
    return_eigendecomp: bool = True,
    n_eigenvalues: int = 10,
) -> dict[str, Any]:
    """Compute the graph Laplacian and optionally its eigendecomposition.

    Parameters
    ----------
    adjacency : np.ndarray
        Square non-negative adjacency matrix of shape (N, N).
    normalization : {"unnormalized", "symmetric", "random_walk"}
        Type of Laplacian normalization.
    return_eigendecomp : bool
        If True, compute eigenvalues and eigenvectors.
    n_eigenvalues : int
        Number of smallest eigenvalues/vectors to return.

    Returns
    -------
    dict with keys:
        ``laplacian`` — the Laplacian matrix (N, N).
        ``eigenvalues`` — first n_eigenvalues eigenvalues (if return_eigendecomp).
        ``eigenvectors`` — first n_eigenvalues eigenvectors (if return_eigendecomp).
        ``n_connected_components`` — number of zero eigenvalues (if return_eigendecomp).
    """
    adjacency = np.asarray(adjacency, dtype=float)
    if adjacency.ndim != 2 or adjacency.shape[0] != adjacency.shape[1]:
        raise ValueError("adjacency must be a square 2-D matrix")
    if np.any(adjacency < 0):
        raise ValueError("adjacency must be non-negative")

    N = adjacency.shape[0]
    if return_eigendecomp and n_eigenvalues > N:
        raise ValueError(f"n_eigenvalues ({n_eigenvalues}) must be <= N ({N})")

    eps = 1e-12
    degree = adjacency.sum(axis=1)
    D = np.diag(degree)

    if normalization == "unnormalized":
        L = D - adjacency
    elif normalization == "symmetric":
        d_inv_sqrt = np.where(degree > 0, 1.0 / np.sqrt(degree + eps), 0.0)
        D_inv_sqrt = np.diag(d_inv_sqrt)
        eye = np.eye(N)
        L = eye - D_inv_sqrt @ adjacency @ D_inv_sqrt
    elif normalization == "random_walk":
        d_inv = np.where(degree > 0, 1.0 / (degree + eps), 0.0)
        D_inv = np.diag(d_inv)
        eye = np.eye(N)
        L = eye - D_inv @ adjacency
    else:
        raise ValueError(f"Unknown normalization: {normalization!r}")

    result: dict[str, Any] = {"laplacian": L}

    if return_eigendecomp:
        eigenvalues, eigenvectors = np.linalg.eigh(L)
        # eigh returns ascending order
        n_eigs = min(n_eigenvalues, N)
        result["eigenvalues"] = eigenvalues[:n_eigs]
        result["eigenvectors"] = eigenvectors[:, :n_eigs]
        result["n_connected_components"] = int(np.sum(eigenvalues < 1e-8))

    return result

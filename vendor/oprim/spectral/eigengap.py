"""Spectral eigengap detection for determining the number of clusters/factors.

References
----------
Von Luxburg, U. (2007). A tutorial on spectral clustering.
    Statistics and Computing, 17(4), 395-416.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def spectral_eigengap_detect(
    eigenvalues: np.ndarray,
    *,
    method: Literal["largest_gap", "relative", "elbow"] = "largest_gap",
    max_k: int | None = None,
) -> dict[str, Any]:
    """Detect the optimal number of components via eigengap heuristics.

    Parameters
    ----------
    eigenvalues:
        1-D array of eigenvalues (any order; sorted descending internally).
    method:
        ``"largest_gap"`` — position of maximum absolute gap.
        ``"relative"``    — position of maximum ratio between consecutive values.
        ``"elbow"``       — position of maximum concavity (second difference).
    max_k:
        Upper bound on the search range (default: ``len(eigenvalues) - 1``).

    Returns
    -------
    dict with keys:
        ``k_star``     optimal number of components,
        ``gaps``       gap array used for the selected method,
        ``confidence`` relative strength of the chosen gap.
    """
    eigenvalues = np.asarray(eigenvalues, dtype=float)
    if eigenvalues.ndim != 1 or len(eigenvalues) < 2:
        raise ValueError("eigenvalues must be a 1-D array with at least 2 elements")

    # Sort descending
    eigs = np.sort(eigenvalues)[::-1]
    n = len(eigs)
    max_k_eff = min(max_k if max_k is not None else n - 1, n - 1)
    if max_k_eff < 1:
        max_k_eff = 1

    if method == "largest_gap":
        gaps = eigs[:-1] - eigs[1:]
        k_star = int(np.argmax(gaps[:max_k_eff])) + 1

    elif method == "relative":
        gaps = eigs[:-1] / np.maximum(eigs[1:], 1e-10)
        k_star = int(np.argmax(gaps[:max_k_eff])) + 1

    elif method == "elbow":
        d2 = np.diff(np.diff(eigs))
        # Elbow: most concave point (largest -d2)
        gaps = -d2
        search_len = min(max_k_eff, len(gaps))
        k_star = int(np.argmax(gaps[:search_len])) + 1

    else:
        raise ValueError(
            f"Unknown method '{method}'. Choose 'largest_gap', 'relative', or 'elbow'."
        )

    # Confidence: ratio of chosen gap to second-largest gap
    if len(gaps) >= 2:
        sorted_gaps = np.sort(gaps)[::-1]
        best_gap = sorted_gaps[0]
        second_gap = sorted_gaps[1]
        confidence = float(best_gap / second_gap) if second_gap > 1e-14 else 1.0
    else:
        confidence = 1.0

    return {
        "k_star": k_star,
        "gaps": gaps,
        "confidence": confidence,
    }

"""Vector similarity metrics for dense embeddings.

Mathematical definitions
------------------------
cosine   :  (q · c_i) / (‖q‖ · ‖c_i‖)
dot      :  q · c_i
euclidean:  −‖q − c_i‖        (negated: higher = more similar)
manhattan:  −Σ|q_j − c_{i,j}| (negated)

When *normalize=True* and metric ∈ {cosine, dot}, inputs are L2-normalised
before the dot-product, making both metrics equivalent to cosine similarity.

Reference: Manning, Raghavan & Schütze (2008). *Introduction to Information
Retrieval*, Cambridge University Press, §6.3.
"""
from __future__ import annotations

from typing import Literal

import numpy as np


def vector_similarity(
    query: np.ndarray,
    corpus: np.ndarray,
    *,
    metric: Literal["cosine", "dot", "euclidean", "manhattan"] = "cosine",
    normalize: bool = True,
) -> np.ndarray:
    """Compute similarity between a query vector and every row of a corpus.

    Parameters
    ----------
    query : np.ndarray, shape (D,)
        Single query embedding.
    corpus : np.ndarray, shape (N, D)
        Matrix of N corpus embeddings each of dimension D.
    metric : {"cosine", "dot", "euclidean", "manhattan"}, optional
        Similarity function.  Default "cosine".
    normalize : bool, optional
        If True *and* metric ∈ {"cosine", "dot"}, L2-normalise both query and
        corpus rows before computing the dot product.  Has no effect for
        "euclidean" or "manhattan".  Default True.

    Returns
    -------
    np.ndarray, shape (N,)
        Per-row similarity scores.  For "euclidean" and "manhattan" the scores
        are *negated* distances so that higher values always indicate greater
        similarity.

    Raises
    ------
    ValueError
        If ``query.ndim != 1``, ``corpus.ndim != 2``, the dimension D does not
        match, or an unsupported metric is requested.

    Examples
    --------
    >>> import numpy as np
    >>> q = np.array([1.0, 0.0])
    >>> C = np.array([[1.0, 0.0], [0.0, 1.0]])
    >>> vector_similarity(q, C, metric="cosine")
    array([1., 0.])
    """
    _VALID_METRICS = {"cosine", "dot", "euclidean", "manhattan"}

    # --- input validation -------------------------------------------------- #
    query = np.asarray(query, dtype=float)
    corpus = np.asarray(corpus, dtype=float)

    if query.ndim != 1:
        raise ValueError(
            f"query must be 1-D, got shape {query.shape}"
        )
    if corpus.ndim != 2:
        raise ValueError(
            f"corpus must be 2-D, got shape {corpus.shape}"
        )
    if query.shape[0] != corpus.shape[1]:
        raise ValueError(
            f"Dimension mismatch: query has D={query.shape[0]} but corpus has "
            f"D={corpus.shape[1]}"
        )
    if metric not in _VALID_METRICS:
        raise ValueError(
            f"Invalid metric {metric!r}. Must be one of {sorted(_VALID_METRICS)}"
        )

    # --- compute similarity ------------------------------------------------- #
    if metric in {"cosine", "dot"}:
        if normalize:
            q_norm = np.linalg.norm(query)
            if q_norm == 0.0:
                q_unit = query
            else:
                q_unit = query / q_norm

            c_norms = np.linalg.norm(corpus, axis=1, keepdims=True)
            # avoid division by zero for zero-vectors in corpus
            c_norms = np.where(c_norms == 0.0, 1.0, c_norms)
            c_unit = corpus / c_norms
            return c_unit @ q_unit
        else:
            # raw dot product
            return corpus @ query

    elif metric == "euclidean":
        # −‖q − c_i‖
        diff = corpus - query  # broadcast (N, D)
        return -np.linalg.norm(diff, axis=1)

    else:  # manhattan
        diff = corpus - query
        return -np.sum(np.abs(diff), axis=1)

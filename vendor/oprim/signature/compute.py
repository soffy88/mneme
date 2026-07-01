"""Truncated path signature computation.

References
----------
Chen, K.T. (1954). Iterated integrals and exponential homomorphisms.
    Proc. London Math. Soc., 3(4), 502-512.
Lyons, T., Caruana, M. & Lévy, T. (2007). Differential Equations Driven
    by Rough Paths. Springer Lecture Notes in Mathematics 1908.
Chevyrev, I. & Kormilitzin, A. (2016). A Primer on the Signature Method
    in Machine Learning. arXiv:1603.03788.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from oprim.crypto.hashing import sha256_hash
from oprim.serialization.canonical import canonical_json


def _compute_signature(increments: np.ndarray, depth: int) -> np.ndarray:
    """Compute the truncated path signature up to given depth.

    Parameters
    ----------
    increments : np.ndarray
        Shape (n_steps, d). Increments dx_t = x_{t+1} - x_t.
    depth : int
        Truncation depth (1 ≤ depth ≤ 6).

    Returns
    -------
    np.ndarray
        1D array of length 1 + d + d^2 + ... + d^depth.
    """
    n_steps, d = increments.shape

    running = [np.ones(1)]  # level 0: always 1
    for k in range(1, depth + 1):
        running.append(np.zeros(d**k))

    for t in range(n_steps):
        dx = increments[t]  # shape (d,)
        # Update from high to low to avoid using updated values in same step
        for k in range(depth, 0, -1):
            prev = running[k - 1]  # shape (d^(k-1),)
            running[k] += np.outer(prev, dx).ravel()

    return np.concatenate(running)


def _augment_with_time(path: np.ndarray) -> np.ndarray:
    """Prepend a normalised time channel [0, 1] to the path."""
    n = path.shape[0]
    t_col = np.linspace(0.0, 1.0, n).reshape(-1, 1)
    return np.concatenate([t_col, path], axis=1)


def _augment_with_lead_lag(path: np.ndarray) -> np.ndarray:
    """Lead-lag transformation: doubles channels.

    For each dimension i, append the lag-1 version of that channel.
    The first lag value is set to path[0] (no look-ahead).
    """
    n, d = path.shape
    lag = np.empty_like(path)
    lag[0] = path[0]
    lag[1:] = path[:-1]
    return np.concatenate([path, lag], axis=1)


def path_signature_compute(
    path: np.ndarray,
    *,
    truncation_depth: int = 4,
    augment_with_time: bool = True,
    augment_with_lead_lag: bool = False,
    return_log_signature: bool = False,
) -> dict[str, Any]:
    """Compute the truncated path signature of a multi-dimensional path.

    Given a d-dimensional path discretised as n_steps points, returns the
    truncated signature up to ``truncation_depth``.  Optionally applies time
    or lead-lag augmentation before computing the signature.

    Parameters
    ----------
    path : np.ndarray
        Shape (n_steps, d).  Each row is a point in R^d.
    truncation_depth : int
        Truncation depth N (1 ≤ N ≤ 6).
    augment_with_time : bool
        If True, prepend a normalised time channel before computing.
    augment_with_lead_lag : bool
        If True, apply lead-lag transformation (doubles channel count).
    return_log_signature : bool
        If True, project the signature onto the Lie algebra basis (depth ≤ 2).
        For depth > 2 the full signature is returned with ``is_log_signature``
        set to False and a note in the result.

    Returns
    -------
    dict with keys:
        signature : np.ndarray
            1D signature (or log-signature) array.
        depth : int
            Truncation depth used.
        channels_used : int
            Number of channels in the (possibly augmented) path.
        augmented_path : np.ndarray
            The path actually used for signature computation.
        is_log_signature : bool
        fingerprint : str
            SHA-256 hex digest of the canonical JSON of signature values.

    Raises
    ------
    ValueError
        If ``path`` is not 2D, has fewer than 2 steps, or depth is out of range.
    """
    path = np.asarray(path, dtype=float)
    if path.ndim != 2:
        raise ValueError(f"path must be 2D (n_steps, d), got shape {path.shape}")
    n_steps, d = path.shape
    if n_steps < 2:
        raise ValueError(f"path must have at least 2 steps, got {n_steps}")
    if not (1 <= truncation_depth <= 6):
        raise ValueError(f"truncation_depth must be 1 ≤ depth ≤ 6, got {truncation_depth}")

    aug_path = path.copy()
    if augment_with_lead_lag:
        aug_path = _augment_with_lead_lag(aug_path)
    if augment_with_time:
        aug_path = _augment_with_time(aug_path)

    channels_used = aug_path.shape[1]
    increments = np.diff(aug_path, axis=0)  # shape (n_steps-1, channels_used)

    sig = _compute_signature(increments, truncation_depth)

    is_log_sig = False
    if return_log_signature and truncation_depth <= 2:
        sig = _project_log_signature(sig, channels_used, truncation_depth)
        is_log_sig = True

    fingerprint = sha256_hash(canonical_json(sig.tolist()).encode("utf-8"))

    return {
        "signature": sig,
        "depth": truncation_depth,
        "channels_used": channels_used,
        "augmented_path": aug_path,
        "is_log_signature": is_log_sig,
        "fingerprint": fingerprint,
    }


def _project_log_signature(
    sig: np.ndarray,
    d: int,
    depth: int,
) -> np.ndarray:
    """Project the truncated signature onto the Lie algebra (Hall basis).

    Level 1: unchanged (d terms).
    Level 2: antisymmetric correction.
      log_sig^{i,j} = X^{i,j} - 0.5 * X^i * X^j  for all (i, j).
    This is the standard first-order correction relating iterated integrals
    to the free Lie algebra.

    Parameters
    ----------
    sig : np.ndarray
        Full truncated signature (output of _compute_signature).
    d : int
        Number of channels.
    depth : int
        Must be 1 or 2.

    Returns
    -------
    np.ndarray
        Log-signature array with same length as ``sig``.
    """
    result = sig.copy()
    if depth >= 2:
        level1 = sig[1 : 1 + d]
        level2_start = 1 + d
        level2 = sig[level2_start : level2_start + d * d]
        log2 = level2 - 0.5 * np.outer(level1, level1).ravel()
        result[level2_start : level2_start + d * d] = log2
    return result

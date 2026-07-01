"""Information-theoretic atomic operations."""

from __future__ import annotations

import numpy as np


def shannon_entropy(
    x: np.ndarray,
    base: float = 2.0,
) -> float:
    """Shannon entropy of a discrete symbol sequence.

    H(X) = -Σ p(x) log_b(p(x))

    Parameters
    ----------
    x : np.ndarray
        1-D array of discrete symbols (integers).
    base : float
        Logarithm base (2.0 for bits, e for nats).

    Returns
    -------
    float
        Entropy value.

    References
    ----------
    .. [1] Shannon, C.E. (1948). A Mathematical Theory of Communication.
    .. [2] Extraction source: Selene project, sel_v2/offline/transfer_entropy.py:_H
    """
    x = np.asarray(x)
    if len(x) == 0:
        return 0.0
    _, counts = np.unique(x, return_counts=True)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    if base == np.e:
        return float(-np.sum(probs * np.log(probs)))
    return float(-np.sum(probs * np.log(probs) / np.log(base)))


def ordinal_pattern(
    x: np.ndarray,
    d: int = 3,
) -> np.ndarray:
    """Encode time series into ordinal patterns (Bandt-Pompe).

    Each window of length d is mapped to its rank permutation index.

    Parameters
    ----------
    x : np.ndarray
        1-D time series.
    d : int
        Embedding dimension (pattern length). Default 3.

    Returns
    -------
    np.ndarray
        Integer array of pattern indices, length = len(x) - d + 1.

    References
    ----------
    .. [1] Bandt, C. & Pompe, B. (2002). Permutation Entropy.
    .. [2] Extraction source: Selene project, sel_v2/offline/transfer_entropy.py:_ordinal_pattern
    """
    x = np.asarray(x, dtype=float)
    n = len(x) - d + 1
    if n <= 0:
        raise ValueError(f"Series too short: len={len(x)}, d={d}")
    from math import factorial
    max_patterns = factorial(d)
    patterns = np.empty(n, dtype=int)
    for i in range(n):
        window = x[i: i + d]
        # Rank the window values
        order = np.argsort(window)
        # Convert permutation to index (Lehmer code)
        idx = 0
        for pos in range(d):
            rank = 0
            for j in range(pos + 1, d):
                if order[j] < order[pos]:
                    rank += 1
            idx = idx * (d - pos) + rank
        patterns[i] = idx
    return patterns


def phase_randomize(
    x: np.ndarray,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Phase-randomization surrogate preserving power spectrum.

    Randomizes Fourier phases while keeping amplitudes intact.
    Used for significance testing of nonlinear dependencies.

    Parameters
    ----------
    x : np.ndarray
        1-D real-valued time series.
    rng : np.random.Generator, optional
        Random number generator.

    Returns
    -------
    np.ndarray
        Surrogate series with same power spectrum but randomized phases.

    References
    ----------
    .. [1] Theiler, J. et al. (1992). Testing for nonlinearity in time series.
    .. [2] Extraction source: Selene project, sel_v2/offline/transfer_entropy.py:phase_randomize
    """
    if rng is None:
        rng = np.random.default_rng()
    n = len(x)
    ft = np.fft.rfft(x)
    phases = rng.uniform(0, 2 * np.pi, len(ft))
    phases[0] = 0  # preserve DC component
    if n % 2 == 0:
        phases[-1] = 0  # preserve Nyquist for even-length
    ft_rand = ft * np.exp(1j * phases)
    return np.fft.irfft(ft_rand, n=n)

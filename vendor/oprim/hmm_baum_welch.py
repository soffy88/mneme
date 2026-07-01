"""oprim.hmm_baum_welch — Fit a Gaussian HMM via the Baum-Welch algorithm."""
from __future__ import annotations

from typing import Any


def hmm_baum_welch(
    observations: Any,
    *,
    n_states: int,
    max_iter: int = 100,
    covariance_type: str = "diag",
    random_state: int | None = 42,
) -> dict[str, Any]:
    """Fit a Gaussian HMM using Baum-Welch (EM) via obase.HmmlearnRuntime.

    Composites:
        - obase.hmmlearn_runtime.HmmlearnRuntime.fit

    Args:
        observations: 1-D or 2-D array-like of shape (T,) or (T, D).
        n_states: Number of hidden states.
        max_iter: Maximum EM iterations.
        covariance_type: Covariance structure — "diag", "full", "tied", "spherical".
        random_state: Seed for reproducibility.

    Returns:
        Model dict with ``transmat``, ``means``, ``covars``, ``startprob``,
        ``n_states``, and ``_model`` (required by hmm_viterbi).

    Raises:
        ImportError: If hmmlearn is not installed (pip install obase[hmmlearn]).
    """
    from obase.hmmlearn_runtime import HmmlearnRuntime  # noqa: PLC0415

    return HmmlearnRuntime.fit(
        observations,
        n_states=n_states,
        max_iter=max_iter,
        covariance_type=covariance_type,
        random_state=random_state,
    )

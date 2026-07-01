"""oprim.hmm_viterbi — Decode HMM hidden-state sequence via Viterbi algorithm."""
from __future__ import annotations

from typing import Any


def hmm_viterbi(
    observations: Any,
    *,
    model: dict[str, Any],
) -> list[int]:
    """Decode most-likely hidden states using Viterbi via obase.HmmlearnRuntime.

    Composites:
        - obase.hmmlearn_runtime.HmmlearnRuntime.predict

    Args:
        observations: 1-D or 2-D array-like matching the training shape.
        model: Dict returned by hmm_baum_welch (must contain ``_model`` key).

    Returns:
        List of integer state indices, length == len(observations).

    Raises:
        ImportError: If hmmlearn is not installed.
        ValueError: If *model* is missing the ``_model`` key.
    """
    from obase.hmmlearn_runtime import HmmlearnRuntime  # noqa: PLC0415

    return HmmlearnRuntime.predict(observations, model=model)

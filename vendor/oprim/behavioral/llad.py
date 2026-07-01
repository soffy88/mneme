"""Large Loss Aversion Degree (LLAD) — Barberis (2013) / Ingersoll-Jin (2013)."""

from __future__ import annotations

from typing import Any


def large_loss_aversion_degree(
    *,
    alpha: float,
    beta: float,
    loss_aversion: float,
    return_distribution_params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute the Large Loss Aversion Degree (LLAD).

    Mathematical definition:

        LLAD = (beta / alpha) * loss_aversion^(1/beta)

    The LLAD measures how strongly the agent overweights large losses relative
    to gains as payoff magnitudes grow.  Under a Pareto distribution with tail
    index ``xi`` the relevant threshold is ``xi / (xi - 1)``; LLAD > threshold
    indicates the CPT functional is well-posed (finite expected value).

    Parameters
    ----------
    alpha : float
        Gain curvature of the CPT value function. Must be in (0, 1].
    beta : float
        Loss curvature of the CPT value function. Must be in (0, 1].
    loss_aversion : float
        Loss aversion coefficient lambda. Must be >= 1.
    return_distribution_params : dict or None
        Optional distribution parameters.  If provided and contains key
        ``"tail_index"`` (Pareto tail index > 1), the well-posedness
        threshold is computed as ``tail_index / (tail_index - 1)`` and
        ``well_posed`` is set accordingly.  Otherwise ``well_posed`` is None.

    Returns
    -------
    dict with keys:
        - ``llad`` (float): computed LLAD value.
        - ``well_posed`` (bool or None): whether LLAD > threshold.
        - ``llad_threshold`` (float or None): distribution-specific threshold.

    Raises
    ------
    ValueError
        If parameter constraints are violated.
    """
    if not (0 < alpha <= 1):
        raise ValueError(f"alpha must be in (0, 1], got {alpha!r}")
    if not (0 < beta <= 1):
        raise ValueError(f"beta must be in (0, 1], got {beta!r}")
    if loss_aversion < 1:
        raise ValueError(f"loss_aversion must be >= 1, got {loss_aversion!r}")

    llad = (beta / alpha) * loss_aversion ** (1.0 / beta)

    threshold: float | None = None
    well_posed: bool | None = None

    if return_distribution_params is not None:
        tail_index = return_distribution_params.get("tail_index")
        if tail_index is not None:
            if tail_index <= 1:
                raise ValueError(
                    f"tail_index must be > 1 for a finite mean Pareto, got {tail_index!r}"
                )
            threshold = tail_index / (tail_index - 1.0)
            well_posed = bool(llad > threshold)

    return {"llad": llad, "well_posed": well_posed, "llad_threshold": threshold}

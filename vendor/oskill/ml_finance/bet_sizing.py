"""Convert ML probabilities to position sizes (López de Prado 2018 Ch.10)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import norm


def bet_sizing(
    probabilities: np.ndarray | pd.Series,
    *,
    n_classes: int = 2,
    method: Literal["sigmoid", "average_concurrent", "kelly_fractional"] = "sigmoid",
    side: np.ndarray | pd.Series | None = None,
    step_size: float | None = None,
    max_position: float = 1.0,
) -> np.ndarray | pd.Series:
    """Convert ML probabilities to position sizes (López de Prado 2018 Ch.10).

    Translates model output probabilities into actionable position sizes.
    The sigmoid method centers the position at the indifference probability
    (1/n_classes) and maps to [-max_position, max_position].

    sigmoid:
        z = (p - 1/n_classes) / sqrt(p * (1-p))  for binary (n_classes=2)
        m = 2 * norm.cdf(z) - 1
        If side provided: m *= side (long/short direction)

    kelly_fractional:
        f = p - (1-p) / b  where b = win/loss ratio (assumed 1.0)
        Conservative Kelly = f * 0.5

    Args:
        probabilities: Model output probabilities in [0, 1] (length N).
        n_classes: Number of outcome classes (default 2 for binary).
        method: Sizing method — 'sigmoid' (default), 'average_concurrent',
                or 'kelly_fractional'.
        side: Optional directional signal {-1, +1}. If provided, sizes are
              multiplied by side to get long/short positions.
        step_size: If set, round sizes to nearest step_size increment.
        max_position: Maximum absolute position size (default 1.0).

    Returns:
        Position sizes array in [-max_position, max_position].
        Returns same type as input (pd.Series or np.ndarray).
    """
    is_series = isinstance(probabilities, pd.Series)
    if is_series:
        p = probabilities.values.astype(np.float64)
        index = probabilities.index
    else:
        p = np.asarray(probabilities, dtype=np.float64)
        index = None

    if side is not None:
        if isinstance(side, pd.Series):
            side_arr = side.values.astype(np.float64)
        else:
            side_arr = np.asarray(side, dtype=np.float64)
    else:
        side_arr = None

    # Clip probabilities to avoid log(0) or division by zero
    eps = 1e-8
    p_safe = np.clip(p, eps, 1.0 - eps)

    p_indiff = 1.0 / n_classes

    if method == "sigmoid":
        # Standardized distance from indifference
        denom = np.sqrt(p_safe * (1.0 - p_safe))
        denom = np.where(denom < eps, eps, denom)
        z = (p_safe - p_indiff) / denom
        sizes = 2.0 * norm.cdf(z) - 1.0

    elif method == "average_concurrent":
        # Simple linear scaling centered at indifference
        sizes = (p_safe - p_indiff) / (1.0 - p_indiff)
        sizes = np.clip(sizes, -1.0, 1.0)

    elif method == "kelly_fractional":
        # Kelly: f = p - (1-p)/b, b = 1 (symmetric payoff assumed)
        # Conservative: multiply by 0.5
        b = 1.0  # symmetric win/loss ratio
        f = p_safe - (1.0 - p_safe) / b  # = 2p - 1
        sizes = 0.5 * f  # conservative Kelly (half-Kelly)

    else:
        raise ValueError(f"Unknown method: {method!r}")

    # Apply side direction
    if side_arr is not None:
        sizes = sizes * side_arr

    # Clip to [-max_position, max_position]
    sizes = np.clip(sizes, -max_position, max_position)

    # Round to step size
    if step_size is not None and step_size > 0:
        sizes = np.round(sizes / step_size) * step_size
        sizes = np.clip(sizes, -max_position, max_position)

    if is_series:
        return pd.Series(sizes, index=index)
    return sizes

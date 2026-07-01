"""Numerical stability atomic operations."""

from __future__ import annotations

import logging
import warnings

import numpy as np
from scipy.special import logsumexp as _scipy_logsumexp
from scipy.special import softmax as _scipy_softmax


def logsumexp_safe(
    x: np.ndarray,
    axis: int | None = None,
    weights: np.ndarray | None = None,
    keepdims: bool = False,
) -> np.ndarray:
    """Numerically stable log(sum(exp(x))).

    Computes log(sum(exp(x))) or log(sum(weights * exp(x))) if weights given.

    Parameters
    ----------
    x : np.ndarray
        Input array.
    axis : int | None
        Axis to reduce over.
    weights : np.ndarray | None
        Optional weights (applied inside exp).
    keepdims : bool
        Whether to keep reduced dimensions.

    Returns
    -------
    np.ndarray
        Result of log(sum(exp(x))) or log(sum(weights * exp(x))).
    """
    x = np.asarray(x, dtype=np.float64)
    return np.asarray(_scipy_logsumexp(x, axis=axis, b=weights, keepdims=keepdims))


def softmax_safe(
    x: np.ndarray,
    axis: int = -1,
    temperature: float = 1.0,
) -> np.ndarray:
    """Numerically stable softmax with temperature scaling.

    softmax(x/T) = exp(x/T) / sum(exp(x/T))

    Parameters
    ----------
    x : np.ndarray
        Input logits.
    axis : int
        Axis to compute softmax over.
    temperature : float
        Temperature parameter (must be > 0).

    Returns
    -------
    np.ndarray
        Probability distribution (sums to 1 along axis).
    """
    if temperature <= 0:
        raise ValueError("temperature must be > 0")

    x = np.asarray(x, dtype=np.float64)
    scaled = x / temperature
    return _scipy_softmax(scaled, axis=axis)


def clip_with_warning(
    x: np.ndarray | float,
    lower: float | None = None,
    upper: float | None = None,
    warning_threshold_pct: float = 0.05,
    logger: logging.Logger | None = None,
) -> np.ndarray | float:
    """Clip values with warning when clipping exceeds threshold.

    Parameters
    ----------
    x : np.ndarray | float
        Input values.
    lower, upper : float | None
        Clip bounds.
    warning_threshold_pct : float
        Fraction of values clipped that triggers a warning.
    logger : logging.Logger | None
        Logger for warnings. None = use warnings module.

    Returns
    -------
    np.ndarray | float
        Clipped values.

    Notes
    -----
    NaN values are not counted in clipped_count or the proportion denominator.
    """
    arr = np.asarray(x, dtype=np.float64)
    is_scalar = np.ndim(x) == 0

    n = np.sum(~np.isnan(arr))
    clipped_count = 0

    if lower is not None:
        clipped_count += int(np.nansum(arr < lower))
    if upper is not None:
        clipped_count += int(np.nansum(arr > upper))

    result = np.clip(arr, lower, upper)

    if n > 0 and clipped_count / n > warning_threshold_pct:
        msg = f"clip_with_warning: {clipped_count}/{int(n)} ({clipped_count/n:.1%}) values clipped"
        if logger is not None:
            logger.warning(msg)
        else:
            warnings.warn(msg, stacklevel=2)

    if is_scalar:
        return float(result)
    return result

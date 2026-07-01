"""Logical predicate primitives.

Pure boolean evaluation, no business concepts.
"""

from __future__ import annotations

from typing import Literal

STABILITY = "experimental"

OperatorType = Literal["gt", "gte", "lt", "lte", "eq", "ne"]


def evaluate_threshold_condition(
    value: float,
    threshold: float,
    op: OperatorType,
) -> bool:
    """Evaluate a threshold predicate.

    Parameters
    ----------
    value : measured value
    threshold : reference threshold
    op : comparison operator ("gt", "gte", "lt", "lte", "eq", "ne")

    Returns
    -------
    True if condition holds, False otherwise

    Raises
    ------
    ValueError : if op is not a valid operator

    Examples
    --------
    >>> evaluate_threshold_condition(0.8, 0.5, "gt")
    True
    >>> evaluate_threshold_condition(0.5, 0.5, "gte")
    True
    """
    if op == "gt":
        return value > threshold
    elif op == "gte":
        return value >= threshold
    elif op == "lt":
        return value < threshold
    elif op == "lte":
        return value <= threshold
    elif op == "eq":
        return value == threshold
    elif op == "ne":
        return value != threshold
    else:
        raise ValueError(f"Unknown operator: {op!r}. Must be one of gt, gte, lt, lte, eq, ne")

"""Compute effortful learning gain (desirable difficulties metric).

Pure algorithm, no LLM.  Measures how much learning gain came from
effortful (desirable difficulty) practice vs. easy practice.

Version: oprim v3.3.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class EffortfulGainResult:
    """Result of effortful gain computation."""

    effortful_gain: float
    easy_gain: float
    net_effortful_advantage: float
    effort_ratio: float  # fraction of practice that was effortful
    overall_gain: float
    confidence: float = 1.0


def compute_effortful_gain(
    effortful_correct_before: int,
    effortful_correct_after: int,
    effortful_total: int,
    easy_correct_before: int,
    easy_correct_after: int,
    easy_total: int,
    *,
    min_sample: int = 3,
) -> EffortfulGainResult:
    """Compute effortful vs. easy learning gain.

    "Effortful" practice = practice with desirable difficulties (spacing,
    interleaving, generation). "Easy" practice = massed, recognition-based.

    The gain is defined as the improvement in accuracy from before to after:
        gain = (correct_after / total) - (correct_before / total)

    The net effortful advantage is effortful_gain - easy_gain.  A positive
    value indicates desirable difficulties are working.

    Parameters
    ----------
    effortful_correct_before, effortful_correct_after : int
        Correct answers before/after effortful practice.
    effortful_total : int
        Total effortful practice items.
    easy_correct_before, easy_correct_after : int
        Correct answers before/after easy practice.
    easy_total : int
        Total easy practice items.
    min_sample : int
        Minimum total items to consider a gain reliable (affects confidence).

    Returns
    -------
    EffortfulGainResult
        Effortful gain, easy gain, net advantage, and confidence.

    Raises
    ------
    ValueError
        If totals are zero or negative.
    """
    if effortful_total <= 0 or easy_total <= 0:
        raise ValueError("effortful_total and easy_total must be positive")

    effort_before = effortful_correct_before / effortful_total
    effort_after = effortful_correct_after / effortful_total
    easy_before = easy_correct_before / easy_total
    easy_after = easy_correct_after / easy_total

    effortful_gain = effort_after - effort_before
    easy_gain = easy_after - easy_before
    net = effortful_gain - easy_gain

    effort_ratio = effortful_total / (effortful_total + easy_total)
    overall_gain = (
        (effortful_correct_after + easy_correct_after)
        / (effortful_total + easy_total)
        - (effortful_correct_before + easy_correct_before)
        / (effortful_total + easy_total)
    )

    # Confidence: based on sample size
    total = effortful_total + easy_total
    if total >= min_sample * 2:
        confidence = 1.0
    elif total >= min_sample:
        confidence = 0.7
    else:
        confidence = 0.4

    return EffortfulGainResult(
        effortful_gain=round(effortful_gain, 4),
        easy_gain=round(easy_gain, 4),
        net_effortful_advantage=round(net, 4),
        effort_ratio=round(effort_ratio, 4),
        overall_gain=round(overall_gain, 4),
        confidence=confidence,
    )


def compute_effortful_gain_from_arrays(
    effortful_before: np.ndarray | list[float],
    effortful_after: np.ndarray | list[float],
    easy_before: np.ndarray | list[float],
    easy_after: np.ndarray | list[float],
) -> EffortfulGainResult:
    """Compute effortful gain from binary correctness arrays.

    Each array contains 0/1 values indicating incorrect/correct per item.

    Parameters
    ----------
    effortful_before, effortful_after : array-like
        Binary correctness arrays for effortful practice.
    easy_before, easy_after : array-like
        Binary correctness arrays for easy practice.

    Returns
    -------
    EffortfulGainResult
    """
    eb = np.asarray(effortful_before, dtype=np.float64)
    ea = np.asarray(effortful_after, dtype=np.float64)
    hb = np.asarray(easy_before, dtype=np.float64)
    ha = np.asarray(easy_after, dtype=np.float64)

    return compute_effortful_gain(
        effortful_correct_before=int(np.sum(eb)),
        effortful_correct_after=int(np.sum(ea)),
        effortful_total=len(eb),
        easy_correct_before=int(np.sum(hb)),
        easy_correct_after=int(np.sum(ha)),
        easy_total=len(hb),
    )

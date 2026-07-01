"""oprim.cmi_verify — Single deterministic CMI causal computation.

3O layer: oprim (single atomic computation, pure stats, no LLM).
Computes causal evidence score: whether intervention produces reliable effect.
A11/A17: deterministic, reproducible, no LLM judgment.
"""

from __future__ import annotations
import numpy as np


def cmi_verify(
    *,
    treatment: list[float],
    control: list[float],
    alpha: float = 0.05,
) -> dict:
    """Compute causal evidence from treatment/control observations.

    Returns: {
        effect_size: float,       # Cohen's d
        p_value: float,           # two-sample t-test p-value
        significant: bool,        # p_value < alpha
        n_treatment: int,
        n_control: int,
        mean_diff: float,         # mean(treatment) - mean(control)
        causal_confidence: str,   # "strong"|"moderate"|"weak"|"none"
    }
    """
    t = np.asarray(treatment, dtype=float)
    c = np.asarray(control, dtype=float)

    if len(t) == 0 or len(c) == 0:
        return {
            "effect_size": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n_treatment": len(treatment),
            "n_control": len(control),
            "mean_diff": 0.0,
            "causal_confidence": "none",
        }

    mean_diff = float(np.mean(t) - np.mean(c))

    # Cohen's d
    pooled_std = (
        np.sqrt((np.var(t, ddof=1) + np.var(c, ddof=1)) / 2) if (len(t) > 1 and len(c) > 1) else 1.0
    )
    effect_size = mean_diff / pooled_std if pooled_std > 0 else 0.0

    # Two-sample Welch's t-test (no scipy dependency — implement directly)
    # t-stat = mean_diff / sqrt(var_t/n_t + var_c/n_c)
    # p-value approximated via normal CDF for large samples, or conservative bound
    var_t = np.var(t, ddof=1) if len(t) > 1 else 0.0
    var_c = np.var(c, ddof=1) if len(c) > 1 else 0.0
    se = np.sqrt(var_t / len(t) + var_c / len(c))
    t_stat = mean_diff / se if se > 0 else 0.0

    # Approximate p-value using normal distribution (conservative for large n)
    from math import erfc, sqrt

    p_value = float(erfc(abs(t_stat) / sqrt(2)))  # two-tailed

    significant = p_value < alpha
    abs_d = abs(effect_size)
    causal_confidence = (
        "strong"
        if significant and abs_d >= 0.8
        else "moderate"
        if significant and abs_d >= 0.5
        else "weak"
        if significant
        else "none"
    )

    return {
        "effect_size": effect_size,
        "p_value": p_value,
        "significant": significant,
        "n_treatment": len(treatment),
        "n_control": len(control),
        "mean_diff": mean_diff,
        "causal_confidence": causal_confidence,
    }

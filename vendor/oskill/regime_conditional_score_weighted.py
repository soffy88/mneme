"""oskill.regime_conditional_score_weighted — Regime-aware weighted composite scoring."""

from __future__ import annotations

from oskill.types import DimContribution, ScoreWeightedResult


def regime_conditional_score_weighted(
    dim_scores: dict[str, float],
    base_weights: dict[str, float],
    regime_weight_overrides: dict[str, dict[str, float]],
    current_regime: str,
) -> ScoreWeightedResult:
    """Compute weighted composite score with per-regime weight overrides.

    Args:
        dim_scores: Raw score per dimension (0-100 scale).
        base_weights: Base weight per dimension (must sum to 1.0).
        regime_weight_overrides: Per-regime multiplier dicts.
        current_regime: Current regime state name.

    Returns:
        ScoreWeightedResult with total_score, contributions, and normalized weights.
    """
    if not dim_scores:
        raise ValueError("dim_scores must be non-empty")
    if abs(sum(base_weights.values()) - 1.0) > 0.001:
        raise ValueError(f"base_weights must sum to 1.0, got {sum(base_weights.values()):.4f}")
    if set(dim_scores.keys()) != set(base_weights.keys()):
        raise ValueError("dim_scores and base_weights must have same keys")

    overrides = regime_weight_overrides.get(current_regime, {})

    # Compute unnormalized weights and multipliers
    unnormalized: dict[str, float] = {}
    multipliers: dict[str, float] = {}
    for dim, base in base_weights.items():
        mult = overrides.get(dim, 1.0)
        multipliers[dim] = mult
        unnormalized[dim] = base * mult

    total_unnorm = sum(unnormalized.values())
    if total_unnorm == 0:
        raise ValueError("Total weight after multiplier became 0")

    weights_used = {dim: w / total_unnorm for dim, w in unnormalized.items()}

    # Compute contributions
    dim_contributions: list[DimContribution] = []
    total_score = 0.0
    for dim in sorted(dim_scores.keys()):
        raw = dim_scores[dim]
        w = weights_used[dim]
        contribution = raw * w
        total_score += contribution
        dim_contributions.append(
            DimContribution(
                dim_name=dim,
                raw_score=raw,
                base_weight=base_weights[dim],
                multiplier=multipliers[dim],
                weight_used=w,
                contribution=contribution,
                is_boosted=multipliers[dim] > 1.0,
                is_dampened=multipliers[dim] < 1.0,
            )
        )

    return ScoreWeightedResult(
        total_score=total_score,
        dim_contributions=dim_contributions,
        weights_used=weights_used,
        regime=current_regime,
    )

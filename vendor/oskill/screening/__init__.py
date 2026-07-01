"""S1 — Candidate pool builder (screening + scoring + filtering)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def candidate_pool_builder(
    *,
    universe: list[dict[str, Any]],
    scoring_fn: Callable[[dict[str, Any]], float],
    filter_rules: list[Callable[[dict[str, Any]], bool]] | None = None,
    top_n: int = 30,
    min_score: float = 0.0,
    regime_aware: bool = False,
    regime: str | None = None,
) -> dict[str, Any]:
    """Build a ranked candidate pool from universe.

    Parameters
    ----------
    universe : list of candidate dicts
    scoring_fn : function(candidate) -> float score
    filter_rules : list of functions that return True to keep, False to reject
    top_n : max candidates to return
    min_score : minimum score threshold
    regime_aware : enable regime-aware mode (injects regime into scoring context)
    regime : current regime name (required when regime_aware=True)

    Returns
    -------
    dict with: candidates (sorted by score desc), stats, metadata
    """
    if regime_aware and not regime:
        raise ValueError("regime parameter required when regime_aware=True")

    if not universe:
        return {
            "candidates": [],
            "stats": {"total": 0, "filtered": 0, "scored": 0},
            "metadata": {"regime_aware": regime_aware, "regime": regime if regime_aware else None},
        }

    # Apply filters
    filtered = universe
    n_rejected = 0
    if filter_rules:
        kept = []
        for candidate in filtered:
            passed = True
            for rule in filter_rules:
                try:
                    if not rule(candidate):
                        passed = False
                        break
                except Exception:
                    passed = False
                    break
            if passed:
                kept.append(candidate)
            else:
                n_rejected += 1
        filtered = kept

    # Inject regime into candidates for scoring if regime_aware
    if regime_aware:
        filtered = [{**c, "_regime": regime} for c in filtered]

    # Score
    scored: list[tuple[float, dict[str, Any]]] = []
    errors = 0
    for candidate in filtered:
        try:
            score = scoring_fn(candidate)
            if score >= min_score:
                scored.append((score, candidate))
        except Exception:
            errors += 1

    # Sort and truncate
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    candidates = [{**c, "_score": s} for s, c in top]

    return {
        "candidates": candidates,
        "stats": {
            "total": len(universe),
            "filtered": n_rejected,
            "scored": len(scored),
            "returned": len(candidates),
            "errors": errors,
        },
        "metadata": {"regime_aware": regime_aware, "regime": regime if regime_aware else None},
    }

"""mneme-core mastery_lower_bound — confidence lower bound of a BKT posterior.

Pure function, no IO.  A single atomic operation (3O oprim): given a point
estimate ``p_learned`` and its posterior std-dev ``sigma``, return the one-sided
confidence lower bound ``p_learned - z * sigma``.

This is the SAME formula ``is_mastered`` applies inline for the quantitative
gate.  Per 3O H1-prim (oprim must not call sibling oprim) the formula is NOT
imported into ``is_mastered``; it stays inlined there and a consistency test
(``test_mastery_lower_bound``) pins the two forms to agree bit-for-bit.

Default ``z=0.84`` mirrors ``mastery_gate.Z`` (~80 % one-sided confidence).  The
constant is duplicated as a literal on purpose (no cross-oprim import); the
consistency test guards against drift.
"""

from __future__ import annotations


def mastery_lower_bound(p_learned: float, *, sigma: float, z: float = 0.84) -> float:
    """Return the one-sided confidence lower bound ``p_learned - z * sigma``.

    Args:
        p_learned: BKT point estimate of P(learned), in [0, 1].
        sigma: posterior standard deviation (binomial approximation upstream).
        z: z-score for the desired one-sided confidence (default 0.84 ≈ 80 %).

    Returns:
        The lower bound; may be negative when ``z * sigma > p_learned`` (callers
        that need a probability clamp it, e.g. ``max(0.0, ...)``).
    """
    return p_learned - z * sigma

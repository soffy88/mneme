"""Tests for mastery_lower_bound — §10 verification (4th oprim, ≥5 scenarios).

The final scenario pins the standalone element against the formula ``is_mastered``
applies inline, so the two can never drift (3O forbids importing one oprim into
the other).
"""

import pytest

from mneme_core.oprim.mastery_lower_bound import mastery_lower_bound
from mneme_core.oprim.mastery_gate import Z, QUANTITATIVE_GATE, is_mastered
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
)


def test_formula_correct():
    """lower_bound = p_learned - z * sigma."""
    assert mastery_lower_bound(0.9, sigma=0.1, z=0.84) == pytest.approx(
        0.9 - 0.84 * 0.1
    )
    assert mastery_lower_bound(0.8, sigma=0.05, z=1.0) == pytest.approx(0.75)


def test_sigma_zero_returns_point_estimate():
    """sigma=0 → no confidence penalty → bound equals p_learned."""
    assert mastery_lower_bound(0.73, sigma=0.0) == pytest.approx(0.73)


def test_large_sigma_pulls_bound_down_possibly_negative():
    """Small-n (large sigma) drags the bound below the point estimate, even < 0."""
    # p=0.6, sigma=0.8, z=0.84 → 0.6 - 0.672 = -0.072
    assert mastery_lower_bound(0.6, sigma=0.8) < 0.0


def test_z_boundary():
    """z=0 collapses to the point estimate; larger z lowers the bound monotonically."""
    assert mastery_lower_bound(0.9, sigma=0.1, z=0.0) == pytest.approx(0.9)
    assert mastery_lower_bound(0.9, sigma=0.1, z=2.0) < mastery_lower_bound(
        0.9, sigma=0.1, z=0.84
    )


def test_default_z_matches_mastery_gate_constant():
    """The element's default z is the same ~80% constant the gate uses."""
    assert mastery_lower_bound(0.9, sigma=0.1) == pytest.approx(0.9 - Z * 0.1)


def test_consistency_with_is_mastered_inline():
    """The standalone element reproduces is_mastered's inline gate decision exactly.

    is_mastered inlines ``p - Z*sigma >= threshold``; here we compute the same
    bound via the element and assert the pass/fail verdict agrees on both sides
    of the threshold.
    """
    kp = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
    threshold = QUANTITATIVE_GATE[KnowledgeType.MEMORY]

    def _progress(p_learned, sigma):
        mod = Module(id="m1", name="M1", order=0, knowledge_points=[kp])
        return LearningProgress(
            student_id="s1",
            modules=[mod],
            bkt={"k1": BktPosterior(p_learned=p_learned, sigma=sigma, n_obs=10)},
        )

    # Just above the gate: element bound >= threshold AND is_mastered True.
    passing = _progress(0.95, 0.02)
    assert mastery_lower_bound(0.95, sigma=0.02, z=Z) >= threshold
    assert is_mastered(passing, kp) is True

    # Just below the gate: element bound < threshold AND is_mastered False.
    failing = _progress(0.92, 0.1)
    assert mastery_lower_bound(0.92, sigma=0.1, z=Z) < threshold
    assert is_mastered(failing, kp) is False

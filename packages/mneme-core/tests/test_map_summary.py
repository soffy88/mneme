"""Dedicated map_summary tests (oskill, ≥8) — V2 backfill.

map_summary projects a student's mastery map: per-module counts, per-KP detail,
embedded next-step, and aggregate totals.
"""

import pytest

from mneme_core.oprim.mastery_gate import map_summary
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
)

MASTERED = BktPosterior(0.98, 0.02, 10)
WEAK = BktPosterior(0.5, 0.1, 3)


def _prog(modules, bkt=None, qual=None):
    return LearningProgress(
        student_id="s",
        modules=modules,
        bkt=bkt or {},
        qualitative_mastery=qual or {},
    )


def _mod(kps, order=0, mid="m", name="M"):
    return Module(id=mid, name=name, order=order, knowledge_points=kps)


K1 = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
K2 = KnowledgePoint(id="k2", name="K2", type=KnowledgeType.MEMORY)
CON = KnowledgePoint(id="kc", name="KC", type=KnowledgeType.CONCEPT)


def test_empty_modules_zero_totals():
    s = map_summary(_prog([_mod([])]), now=100.0)
    assert s["total_kps"] == 0
    assert s["total_mastered"] == 0


def test_total_kps_counts_all():
    s = map_summary(_prog([_mod([K1, K2])]), now=100.0)
    assert s["total_kps"] == 2


def test_total_mastered_counts_mastered():
    s = map_summary(_prog([_mod([K1, K2])], bkt={"k1": MASTERED}), now=100.0)
    assert s["total_mastered"] == 1


def test_module_summary_mastered_and_total():
    s = map_summary(_prog([_mod([K1, K2])], bkt={"k1": MASTERED}), now=100.0)
    m = s["modules"][0]
    assert m["mastered"] == 1 and m["total"] == 2


def test_per_kp_detail_fields():
    s = map_summary(_prog([_mod([K1])], bkt={"k1": WEAK}), now=100.0)
    kp = s["modules"][0]["knowledge_points"][0]
    assert kp["id"] == "k1"
    assert kp["p_learned"] == pytest.approx(0.5)
    assert kp["n_obs"] == 3
    assert kp["mastered"] is False


def test_per_kp_detail_when_no_bkt():
    s = map_summary(_prog([_mod([K1])]), now=100.0)
    kp = s["modules"][0]["knowledge_points"][0]
    assert kp["p_learned"] is None and kp["n_obs"] == 0


def test_next_step_embedded():
    s = map_summary(_prog([_mod([K1])]), now=100.0)
    assert s["next"]["action"] in {"probe", "practice", "assess", "review", "complete"}
    assert s["next"]["kc_id"] == "k1"  # brand-new KP is next


def test_qualitative_kp_reflected_in_summary():
    s = map_summary(_prog([_mod([CON])], qual={"kc": True}), now=100.0)
    kp = s["modules"][0]["knowledge_points"][0]
    assert kp["type"] == "concept" and kp["mastered"] is True


def test_modules_sorted_by_order():
    prog = _prog(
        [
            _mod([K2], order=1, mid="m1", name="M1"),
            _mod([K1], order=0, mid="m0", name="M0"),
        ]
    )
    s = map_summary(prog, now=100.0)
    assert [m["module_id"] for m in s["modules"]] == ["m0", "m1"]

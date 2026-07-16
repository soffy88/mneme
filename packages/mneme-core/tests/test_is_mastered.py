"""Dedicated is_mastered tests (oprim, ≥5) — V2 backfill.

is_mastered lives in mastery_gate.py; these focus solely on the gate decision
across quantitative lower-bound, n_min, missing-state, and qualitative-flag paths.
"""


from mneme_core.oprim.mastery_gate import is_mastered
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
)

MEM = KnowledgePoint(id="k", name="K", type=KnowledgeType.MEMORY)
CON = KnowledgePoint(id="k", name="K", type=KnowledgeType.CONCEPT)


def _p(kp, bkt=None, qual=None):
    return LearningProgress(
        student_id="s",
        modules=[Module(id="m", name="M", order=0, knowledge_points=[kp])],
        bkt=bkt or {},
        qualitative_mastery=qual or {},
    )


def test_quant_pass_when_lower_bound_clears_gate():
    # 0.98 - 0.84*0.02 = 0.9632 >= 0.9
    assert is_mastered(_p(MEM, {"k": BktPosterior(0.98, 0.02, 10)}), MEM) is True


def test_quant_fail_when_lower_bound_below_gate():
    # 0.92 - 0.84*0.1 = 0.836 < 0.9
    assert is_mastered(_p(MEM, {"k": BktPosterior(0.92, 0.1, 5)}), MEM) is False


def test_quant_fail_when_n_below_min():
    # High p, tiny sigma, but n_obs=1 < N_MIN
    assert is_mastered(_p(MEM, {"k": BktPosterior(0.99, 0.001, 1)}), MEM) is False


def test_quant_fail_when_no_bkt_state():
    assert is_mastered(_p(MEM, {}), MEM) is False


def test_qualitative_true_from_flag():
    assert is_mastered(_p(CON, qual={"k": True}), CON) is True


def test_qualitative_false_when_flag_absent():
    assert is_mastered(_p(CON, qual={}), CON) is False

"""Dedicated next_objective tests (oskill, ≥8) — V2 backfill.

Covers the 4-level priority chain (pending → review → first-unmastered → complete)
and the PROBE/PRACTICE/ASSESS classification, plus gate-as-cursor skipping.
"""


from mneme_core.oprim.mastery_gate import next_objective
from mneme_core.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
    NextAction,
    PendingQuestion,
    ReviewTask,
)


def _prog(modules, bkt=None, qual=None, pending=None, review=None):
    return LearningProgress(
        student_id="s",
        modules=modules,
        bkt=bkt or {},
        qualitative_mastery=qual or {},
        review_queue=review or [],
        pending_question=pending,
    )


def _mod(kps, order=0, mid="m"):
    return Module(id=mid, name=mid, order=order, knowledge_points=kps)


MEM = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.MEMORY)
CON = KnowledgePoint(id="k1", name="K1", type=KnowledgeType.CONCEPT)


def test_pending_has_top_priority():
    pq = PendingQuestion(
        knowledge_point_id="k1",
        module_id="m",
        prompt="?",
        expected="A",
        qtype="choice",
        question_id="q1",
    )
    step = next_objective(_prog([_mod([MEM])], pending=pq), now=100.0)
    assert step.action == NextAction.ANSWER_PENDING


def test_review_beats_unmastered_practice():
    rt = ReviewTask(knowledge_point_id="k1", due_at=0.0, priority=2)
    step = next_objective(
        _prog([_mod([MEM])], bkt={"k1": BktPosterior(0.5, 0.1, 3)}, review=[rt]),
        now=100.0,
    )
    assert step.action == NextAction.REVIEW


def test_review_not_returned_when_not_due():
    rt = ReviewTask(knowledge_point_id="k1", due_at=200.0, priority=1)
    step = next_objective(
        _prog([_mod([MEM])], bkt={"k1": BktPosterior(0.5, 0.1, 3)}, review=[rt]),
        now=100.0,
    )
    assert step.action != NextAction.REVIEW  # future due → not surfaced


def test_probe_for_brand_new_kp():
    step = next_objective(_prog([_mod([MEM])]), now=100.0)
    assert step.action == NextAction.PROBE


def test_practice_for_existing_unmastered_quant():
    step = next_objective(
        _prog([_mod([MEM])], bkt={"k1": BktPosterior(0.5, 0.1, 3)}), now=100.0
    )
    assert step.action == NextAction.PRACTICE


def test_assess_for_qualitative_kp():
    step = next_objective(
        _prog([_mod([CON])], bkt={"k1": BktPosterior(0.5, 0.1, 3)}), now=100.0
    )
    assert step.action == NextAction.ASSESS


def test_complete_when_all_mastered():
    step = next_objective(
        _prog([_mod([MEM])], bkt={"k1": BktPosterior(0.98, 0.02, 10)}), now=100.0
    )
    assert step.action == NextAction.COMPLETE


def test_mastered_kp_skipped_cursor():
    k2 = KnowledgePoint(id="k2", name="K2", type=KnowledgeType.MEMORY)
    step = next_objective(
        _prog([_mod([MEM, k2])], bkt={"k1": BktPosterior(0.98, 0.02, 10)}),
        now=100.0,
    )
    assert step.kc_id == "k2"  # k1 mastered → skipped


def test_module_order_respected():
    a = KnowledgePoint(id="ka", name="KA", type=KnowledgeType.MEMORY)
    b = KnowledgePoint(id="kb", name="KB", type=KnowledgeType.MEMORY)
    prog = _prog([_mod([b], order=1, mid="m1"), _mod([a], order=0, mid="m0")])
    step = next_objective(prog, now=100.0)
    assert step.kc_id == "ka"  # order-0 module first

"""Dedicated due_reviews tests (oprim, ≥5) — V2 backfill.

due_reviews(queue, now): filter due_at<=now, sort by (priority asc, due_at asc).
It does NOT call oprim.due_compute (3O H1-prim); comparison is inlined.
"""


from mneme_core.oprim.models import ReviewTask
from mneme_core.oprim.spacing import due_reviews


def _t(kc, due, prio):
    return ReviewTask(knowledge_point_id=kc, due_at=due, priority=prio)


def test_empty_queue_returns_empty():
    assert due_reviews([], now=100.0) == []


def test_future_due_filtered_out():
    out = due_reviews([_t("a", 200.0, 1)], now=100.0)
    assert out == []


def test_due_boundary_inclusive():
    out = due_reviews([_t("a", 100.0, 1)], now=100.0)  # due_at == now → due
    assert [t.knowledge_point_id for t in out] == ["a"]


def test_priority_ascending_error_linked_first():
    out = due_reviews([_t("sched", 0.0, 2), _t("err", 50.0, 1)], now=100.0)
    assert [t.knowledge_point_id for t in out] == ["err", "sched"]


def test_due_at_tiebreak_within_same_priority():
    out = due_reviews([_t("late", 80.0, 2), _t("early", 10.0, 2)], now=100.0)
    assert [t.knowledge_point_id for t in out] == ["early", "late"]


def test_mixed_filter_and_sort():
    queue = [
        _t("future", 500.0, 1),  # filtered
        _t("p2", 30.0, 2),
        _t("p1", 40.0, 1),
    ]
    out = due_reviews(queue, now=100.0)
    assert [t.knowledge_point_id for t in out] == ["p1", "p2"]


def test_returns_new_list_not_mutating_input():
    queue = [_t("b", 80.0, 2), _t("a", 10.0, 1)]
    out = due_reviews(queue, now=100.0)
    assert out is not queue
    assert [t.knowledge_point_id for t in queue] == ["b", "a"]  # input order intact

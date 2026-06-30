"""item 8：每日计划交错练习队列（相邻 KC 不同）。无 DB。"""
from types import SimpleNamespace

from services.daily_plan_service import _build_interleaved_queue


def _m(kc, pm):
    return SimpleNamespace(knowledge_point=kc, p_mastery=pm)


def test_interleaved_queue_no_adjacent_same_kc():
    masteries = [_m("A", 0.3), _m("B", 0.2), _m("C", 0.5), _m("D", 0.4)]
    due = {"math": ["A"], "physics": ["B"]}
    weak = {"math": ["C"], "english": ["D"]}
    q = _build_interleaved_queue(masteries, due, weak, {}, {})
    kcs = [x["kc_id"] for x in q]
    assert set(kcs) == {"A", "B", "C", "D"}          # 覆盖全部
    for a, b in zip(kcs, kcs[1:]):
        assert a != b                                 # 相邻 KC 不同（交错红线）


def test_review_source_overrides_weak():
    masteries = [_m("A", 0.3), _m("B", 0.2)]
    due = {"math": ["A"]}
    weak = {"math": ["A"], "physics": ["B"]}          # A 同时到期+薄弱
    q = _build_interleaved_queue(masteries, due, weak, {}, {})
    a_entry = next(x for x in q if x["kc_id"] == "A")
    assert a_entry["source"] == "review"


def test_single_kc_not_interleaved_no_crash():
    masteries = [_m("A", 0.3)]
    q = _build_interleaved_queue(masteries, {"math": ["A"]}, {}, {}, {})
    assert [x["kc_id"] for x in q] == ["A"]


def test_empty_pool():
    assert _build_interleaved_queue([], {}, {}, {}, {}) == []

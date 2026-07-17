"""Tests for oprim.quiz_selection — C2 (W2C)."""

from mneme_core.oprim.models import KnowledgePoint, KnowledgeType
from mneme_core.oprim.quiz_selection import shape_by_difficulty


def _kp(kc_id, difficulty):
    return KnowledgePoint(
        id=kc_id, name=kc_id, type=KnowledgeType.PROCEDURE, difficulty=difficulty
    )


def test_ascending_sorts_easy_to_hard():
    cands = [_kp("c", 0.8), _kp("a", 0.2), _kp("b", 0.5)]
    result = shape_by_difficulty(cands, curve="ascending")
    assert [kp.id for kp in result] == ["a", "b", "c"]


def test_diagnostic_sorts_hard_to_easy():
    cands = [_kp("c", 0.8), _kp("a", 0.2), _kp("b", 0.5)]
    result = shape_by_difficulty(cands, curve="diagnostic")
    assert [kp.id for kp in result] == ["c", "b", "a"]


def test_mixed_zigzags_from_both_ends():
    cands = [_kp("a", 0.1), _kp("b", 0.3), _kp("c", 0.5), _kp("d", 0.7), _kp("e", 0.9)]
    result = shape_by_difficulty(cands, curve="mixed")
    # 升序为 a,b,c,d,e；zigzag 应为 最易,最难,次易,次难,中间 = a,e,b,d,c
    assert [kp.id for kp in result] == ["a", "e", "b", "d", "c"]


def test_does_not_mutate_input_list_order():
    cands = [_kp("c", 0.8), _kp("a", 0.2)]
    original_order = [kp.id for kp in cands]
    shape_by_difficulty(cands, curve="ascending")
    assert [kp.id for kp in cands] == original_order


def test_empty_and_single_candidate():
    assert shape_by_difficulty([], curve="mixed") == []
    single = [_kp("a", 0.5)]
    assert shape_by_difficulty(single, curve="mixed") == single

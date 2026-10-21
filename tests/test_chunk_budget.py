"""认知负荷预算（新组块上限）纯函数 + 偏好校验测试。

工作记忆 3–4 组块 → 单节计划新 KU 总量设上限：apply_chunk_budget 只裁
new_learn、顺延如实记录、关闭时行为与旧版完全一致。不碰 DB。
"""

from __future__ import annotations

from services.daily_plan_prefs_service import _DEFAULT_PREFS, _validate
from services.daily_plan_service import apply_chunk_budget, count_new_concepts


def _tasks():
    return [
        {"type": "review", "title": "复习", "subject": "math", "ku_ids": ["k1"], "priority": 1, "estimated_minutes": 5},
        {"type": "new_learn", "title": "学习4个新知识点", "subject": "math", "ku_ids": ["n1", "n2", "n3", "n4"], "priority": 4, "estimated_minutes": 40},
        {"type": "new_learn", "title": "学习2个新知识点", "subject": "physics", "ku_ids": ["n5", "n6"], "priority": 4, "estimated_minutes": 40},
    ]


def test_count_new_concepts():
    assert count_new_concepts(["a", "b", "c"], {"a"}) == 2
    assert count_new_concepts([], set()) == 0


def test_budget_trims_across_tasks_and_records_deferred():
    tasks, info = apply_chunk_budget(
        _tasks(), enabled=True, limit=3, known_kp_set={"k1"},
        filler_ku_ids=["k1"], item_cap=2,
    )
    new_tasks = [t for t in tasks if t["type"] == "new_learn"]
    assert [t["ku_ids"] for t in new_tasks] == [["n1", "n2", "n3"]]
    assert info["new_ku_count"] == 3
    assert info["deferred_ku_ids"] == ["n4", "n5", "n6"]
    assert info["filler_ku_ids"] == ["k1"]  # 有顺延才用交错练习填充
    # 非 new_learn 任务原样保留且被标注新概念数（k1 已知 → 0）
    review = [t for t in tasks if t["type"] == "review"][0]
    assert review["new_concept_count"] == 0
    assert new_tasks[0]["new_concept_count"] == 4  # 标注的是裁剪前的新概念数


def test_budget_disabled_is_passthrough():
    tasks, info = apply_chunk_budget(
        _tasks(), enabled=False, limit=3, known_kp_set=set(), filler_ku_ids=["k1"],
    )
    assert len(tasks) == 3
    assert info["deferred_ku_ids"] == []
    assert info["filler_ku_ids"] == []
    assert info["new_ku_count"] == 6


def test_budget_limit_none_is_unlimited():
    tasks, info = apply_chunk_budget(
        _tasks(), enabled=True, limit=None, known_kp_set=set(),
    )
    assert len(tasks) == 3 and info["new_ku_count"] == 6


def test_budget_zero_defers_all_new():
    tasks, info = apply_chunk_budget(
        _tasks(), enabled=True, limit=0, known_kp_set=set(),
    )
    assert [t["type"] for t in tasks] == ["review"]
    assert info["deferred_ku_ids"] == ["n1", "n2", "n3", "n4", "n5", "n6"]


def test_prefs_defaults_and_validation():
    assert _DEFAULT_PREFS["new_ku_per_session"] == 3
    assert _DEFAULT_PREFS["chunk_budget_enabled"] is True
    assert _validate({"new_ku_per_session": 5}) is None
    assert _validate({"new_ku_per_session": None}) is None
    assert _validate({"new_ku_per_session": -1}) is not None
    assert _validate({"new_ku_per_session": True}) is not None  # bool 不是 int
    assert _validate({"chunk_budget_enabled": False}) is None
    assert _validate({"chunk_budget_enabled": 1}) is not None

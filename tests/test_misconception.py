"""L3 误解诊断骨架：干扰项精确映射 + KU 名关键词退回。纯函数。"""

from oprim.misconception import (
    DISTRACTOR_MAP,
    MISCONCEPTIONS,
    diagnose_misconception,
)


def test_registry_integrity():
    """登记表：id 唯一、字段齐全、科目合法、关键词非空。"""
    ids = [m["id"] for m in MISCONCEPTIONS]
    assert len(ids) == len(set(ids)), "误解 id 有重复"
    for m in MISCONCEPTIONS:
        assert m["subject"] in {"math", "physics"}, m["id"]
        assert m["id"] == m["id"].upper()
        assert m["label"] and m["remediation"]
        assert m["keywords"] and all(k.strip() for k in m["keywords"])


def test_new_seed_entries_diagnosable():
    """抽查教研补充条目可经关键词命中。"""
    m = diagnose_misconception("physics", "牛顿第三定律的理解")
    assert m is not None and m["id"] == "PHYS-N3-EQUAL"
    m = diagnose_misconception("math", "一元一次不等式的解法")
    assert m is not None and m["id"] == "MATH-INEQ-NEG-MULT"


def test_heuristic_match_by_keyword():
    m = diagnose_misconception("math", "负数的相反数与绝对值")
    assert m is not None and m["id"] == "MATH-NEG-SIGN"
    assert m["precision"] == "heuristic"
    assert "remediation" in m


def test_physics_force_motion_misconception():
    m = diagnose_misconception("physics", "牛顿第一定律与惯性")
    assert m is not None and m["id"] == "PHYS-FORCE-MOTION"


def test_no_match_returns_none():
    assert diagnose_misconception("math", "完全无关的知识点名XYZ") is None


def test_subject_isolation():
    # 物理误解不会匹配数学 KU
    assert diagnose_misconception("math", "电路串联并联") is None


def test_exact_distractor_map_takes_priority():
    # 临时注入一条精确映射，验证走 exact 分支
    DISTRACTOR_MAP[("KU-TEST", "B")] = "MATH-FRAC-OP"
    try:
        m = diagnose_misconception("math", "无关名", ku_id="KU-TEST", distractor="b")
        assert m is not None and m["id"] == "MATH-FRAC-OP"
        assert m["precision"] == "exact"
    finally:
        DISTRACTOR_MAP.pop(("KU-TEST", "B"), None)

"""L3 误解诊断骨架：干扰项精确映射 + KU 名关键词退回。纯函数。"""

from oprim.misconception import DISTRACTOR_MAP, diagnose_misconception


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

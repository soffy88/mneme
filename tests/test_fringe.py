"""知识空间理论(KST) fringe 分类 + 掌握门控（教育理念 01）。纯函数,确定性。"""

from oprim.prereq_graph import annotate_fringe, fringe_status


def test_mastered():
    assert fringe_status(0.8, [], {}) == "mastered"
    assert fringe_status(0.6, [], {}) == "mastered"  # 阈值边界


def test_learning_in_progress():
    # 在学中：不管前置如何，都是 learning（不锁已在学的）
    assert fringe_status(0.3, ["A"], {"A": 0.0}) == "learning"


def test_learnable_outer_fringe():
    # 未开始 + 前置全掌握 = 可学
    assert fringe_status(None, [], {}) == "learnable"
    assert fringe_status(None, ["A", "B"], {"A": 0.7, "B": 0.9}) == "learnable"
    assert fringe_status(0.02, ["A"], {"A": 0.8}) == "learnable"  # 极低=未开始


def test_locked_prereq_not_met():
    # 未开始 + 存在未掌握前置 = 锁定（掌握门控）
    assert fringe_status(None, ["A", "B"], {"A": 0.7, "B": 0.3}) == "locked"
    assert fringe_status(None, ["A"], {}) == "locked"  # 前置无记录=未掌握


def test_annotate_batch():
    items = [
        {"id": "U1", "prerequisites": [], "p_mastery": None},
        {"id": "U2", "prerequisites": ["U1"], "p_mastery": None},
        {"id": "U3", "prerequisites": ["U1"], "p_mastery": 0.9},
    ]
    mastery = {"U3": 0.9}
    out = annotate_fringe(items, mastery)
    got = {o["id"]: o["fringe"] for o in out}
    assert got == {"U1": "learnable", "U2": "locked", "U3": "mastered"}
    # 不改原字段
    assert out[0]["id"] == "U1" and "prerequisites" in out[0]

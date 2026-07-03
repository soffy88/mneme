"""KC→课标对齐表：全覆盖 KC_LIST、编码合法、素养/水平合法、派生默认可用。"""

from data.curriculum_std import (
    LITERACY_LEVELS,
    is_valid_literacy,
    is_valid_std_code,
)
from data.guangdong_math_kc import KC_LIST
from data.kc_std_alignment import KC_STD_ALIGN, get_alignment


def test_covers_all_kcs():
    """每个 GDMATH KC 都有课标对齐，不漏。"""
    kc_ids = {k["kc_id"] for k in KC_LIST}
    mapped = set(KC_STD_ALIGN)
    assert mapped == kc_ids, f"未对齐: {kc_ids - mapped}; 多余: {mapped - kc_ids}"


def test_all_std_codes_valid():
    for kc_id, rec in KC_STD_ALIGN.items():
        assert is_valid_std_code(rec["std"]), f"{kc_id} 挂了非法编码 {rec['std']}"
        assert rec["level"] in LITERACY_LEVELS, kc_id


def test_alignment_derives_literacy_by_domain():
    """未显式覆盖时按领域派生素养默认（走 suggest_literacy 单源）。"""
    a = get_alignment("GDMATH-CONIC-01")  # 解析几何 → GM 领域
    assert a["primary_std_code"] == "GB-MATH-GZ-XBX-GEOM-ANALY"
    assert a["literacy_tags"] and all(is_valid_literacy(t) for t in a["literacy_tags"])
    assert a["target_level"] == "L2"


def test_explicit_literacy_override():
    a = get_alignment("GDMATH-STAT-02")
    assert "GB-MATH-CL-GZ-MM" in a["literacy_tags"]  # 显式覆盖生效


def test_all_literacy_tags_valid():
    for kc_id in KC_STD_ALIGN:
        a = get_alignment(kc_id)
        assert a["literacy_tags"], f"{kc_id} 无素养标签"
        for t in a["literacy_tags"]:
            assert is_valid_literacy(t), f"{kc_id} 非法素养 {t}"


def test_unknown_kc_returns_none():
    assert get_alignment("GDMATH-NOPE-99") is None

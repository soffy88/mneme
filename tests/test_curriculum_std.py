"""课标对齐骨架：编码唯一/合法、素养校验、领域默认素养建议。纯数据+纯函数。"""

import re

from data.curriculum_std import (
    LITERACY_TAGS,
    STD_NODES,
    get_node,
    is_valid_literacy,
    is_valid_std_code,
    suggest_literacy,
)

_CODE_RE = re.compile(r"^GB-MATH-(JY|GZ)-[A-Z0-9-]+$")


def test_std_codes_unique_and_wellformed():
    codes = [n["code"] for n in STD_NODES]
    assert len(codes) == len(set(codes)), "课标主编码有重复"
    for n in STD_NODES:
        assert _CODE_RE.match(n["code"]), n["code"]
        assert n["seg"] in {"JY", "GZ"}
        assert n["domain"] in {"NA", "GM", "SP", "PA"}
        assert n["kind"] in {"domain", "topic", "unit"}
        assert n["name"]


def test_literacy_tags_unique():
    codes = [t["code"] for t in LITERACY_TAGS]
    assert len(codes) == len(set(codes))
    # 义教 12（含初中抽象能力 CO）+ 高中 6
    assert sum(t["seg"] == "JY" for t in LITERACY_TAGS) == 12
    assert sum(t["seg"] == "GZ" for t in LITERACY_TAGS) == 6


def test_lookup_and_validation():
    assert is_valid_std_code("GB-MATH-GZ-XBX-FUNC-DERIV")
    assert get_node("GB-MATH-GZ-XBX-FUNC-DERIV")["name"] == "一元函数的导数及其应用"
    assert not is_valid_std_code("GB-MATH-GZ-NOPE")


def test_literacy_validation_with_levels():
    assert is_valid_literacy("GB-MATH-CL-GZ-MO")
    assert is_valid_literacy("GB-MATH-CL-GZ-MO-L2")  # 带三级水平后缀
    assert not is_valid_literacy("GB-MATH-CL-GZ-XX")


def test_suggest_literacy_by_domain():
    assert "GB-MATH-CL-GZ-MO" in suggest_literacy("NA", "GZ")
    assert "GB-MATH-CL-JY-JZ" in suggest_literacy("GM", "JY")
    assert suggest_literacy("ZZ", "JY") == []

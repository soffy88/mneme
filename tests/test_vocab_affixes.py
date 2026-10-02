"""services/vocab_affixes.py 的展示格式与校验测试。

用户需求里的展示契约（`前缀·词根·后缀`，用 · 隔开）是**渲染层依赖**：
分隔符或空段处理一变，前端就错位。所以必须钉死，尤其是
「缺段不留空占位」—— 渲染成 `pre · dict ·` 会在卡片上多出一个空格子。
"""

from __future__ import annotations

from services.vocab_affixes import (
    AFFIX_SEPARATOR,
    affix_payload,
    format_affix_chain,
    validate_segment,
)


# ── 展示串 ────────────────────────────────────────────────────────────────


def test_three_segments():
    assert format_affix_chain("dis", "cover", None) == "dis · cover"


def test_prefix_root_suffix_all_three():
    assert format_affix_chain("pre", "dict", "able") == "pre · dict · able"


def test_root_suffix():
    assert format_affix_chain(None, "dict", "able") == "dict · able"


def test_root_only():
    assert format_affix_chain(None, "cap", None) == "cap"


def test_missing_segments_leave_no_empty_placeholder():
    """关键：不能渲染成 'pre · dict · ' 这种尾部空占位。"""
    out = format_affix_chain("pre", "dict", None)
    assert not out.endswith(AFFIX_SEPARATOR)
    assert out.count(AFFIX_SEPARATOR) == 1
    assert "  " not in out


def test_all_empty_returns_empty_string():
    assert format_affix_chain(None, None, None) == ""
    assert format_affix_chain("", "  ", "") == ""


def test_whitespace_stripped():
    assert format_affix_chain(" pre ", " dict ", " able ") == "pre · dict · able"


def test_separator_is_halfwidth_midpoint_with_spaces():
    assert AFFIX_SEPARATOR == " · "
    assert format_affix_chain("a", "b", "c").count("·") == 2


# ── 段校验 ────────────────────────────────────────────────────────────────


def test_validate_accepts_normal():
    assert validate_segment("dict", max_len=48) == "dict"
    assert validate_segment("-able", max_len=32) == "-able"
    assert validate_segment("capere", max_len=48) == "capere"


def test_validate_rejects_chinese():
    """词根段应是拉丁字母形态；混入中文说明解析错了，直接拒。"""
    assert validate_segment("说", max_len=48) is None
    assert validate_segment("dict说", max_len=48) is None


def test_validate_rejects_punctuation_heavy():
    assert validate_segment("pre...,", max_len=32) is None
    assert validate_segment("a+b", max_len=32) is None


def test_validate_rejects_empty_and_overlong():
    assert validate_segment("", max_len=32) is None
    assert validate_segment(None, max_len=32) is None
    assert validate_segment("x" * 33, max_len=32) is None


def test_validate_rejects_no_letter():
    assert validate_segment("123", max_len=32) is None
    assert validate_segment("-", max_len=32) is None


# ── 载荷 ──────────────────────────────────────────────────────────────────


def test_payload_includes_renderable_chain():
    p = affix_payload(prefix="pre", root="dict", suffix="able",
                      meaning_cn="说", origin="拉丁 dicere", source="WLLM",
                      confidence=0.8)
    assert p["chain"] == "pre · dict · able"
    assert p["root"] == "dict"
    assert p["meaning_cn"] == "说"
    assert p["confidence"] == 0.8


def test_payload_normalises_empty_optionals_to_none():
    p = affix_payload(prefix="", root="cap", suffix=None)
    assert p["prefix"] is None
    assert p["suffix"] is None
    assert p["chain"] == "cap"
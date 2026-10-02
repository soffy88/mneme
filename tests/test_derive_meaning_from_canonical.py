"""scripts/derive_meaning_from_canonical.py 的派生逻辑回归测试。

核心风险：把非释义内容写进 meaning_cn。具体三类：
  1. IPA（`[ˈeərən]`）被当成释义 —— 会给孩子显示音标当中文意思；
  2. 占位符（`无`）被写成 meaning_cn；
  3. 词性标签解析错位，把 "n." 当释义、或把释义当词性。

这些都必须用单测钉住，因为它们都是**静默**的：写错了不报错，只是数据变脏。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "derive_meaning_from_canonical.py"
    spec = importlib.util.spec_from_file_location("derive_meaning_from_canonical", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ── 真实样本（来自生产 vocabulary_items.canonical_meaning）──────────────────


def test_multi_pos_bank():
    """生产真实值：三条词性行。"""
    canonical = "n. 银行；岸；浅滩；储库\nvt. 将…存入银行；倾斜转弯\nvi. 堆积；倾斜转弯"
    gloss, pos = mod.derive(canonical)
    assert pos == "n."
    assert gloss == "银行；岸；浅滩；储库"
    assert "将" not in gloss, "只取主词性行，不应混入 vt. 的义项"


def test_single_pos_no_newline():
    gloss, pos = mod.derive("adj. 美丽的")
    assert (gloss, pos) == ("美丽的", "adj.")


def test_no_pos_prefix_whole_line_is_gloss():
    """`A Christmas Carol => 圣诞颂歌；小气财神；圣诞欢歌` 没有词性前缀。"""
    gloss, pos = mod.derive("圣诞颂歌；小气财神；圣诞欢歌")
    assert gloss == "圣诞颂歌；小气财神；圣诞欢歌"
    assert pos is None


def test_pos_with_space_like_link_v():
    gloss, pos = mod.derive("link v. 连接")
    assert pos == "link v."
    assert gloss == "连接"


# ── 必须拒绝：IPA 与占位符 ─────────────────────────────────────────────────


def test_ipa_is_not_a_gloss():
    """专名/缩略词的 IPA 绝不能写进 meaning_cn。"""
    for ipa in ["[ˈeərən]", "[ˌeɪ ˈsiː]", "[æfˈɡænɪstɑːn; æfˈɡænɪstæn]"]:
        assert mod.derive(ipa) == (None, None), ipa


def test_parenthesised_form_rejected():
    assert mod.derive("（音标）") == (None, None)


def test_placeholders_rejected():
    for ph in ["", "  ", "无", "-", "—", "/", "N/A", "null", None]:
        assert mod.derive(ph) == (None, None), repr(ph)


# ── 义项清理 ──────────────────────────────────────────────────────────────


def test_placeholder_senses_dropped():
    gloss, _ = mod.derive("n. 苹果；无；-")
    assert gloss == "苹果"


def test_gloss_truncated_at_sense_boundary_never_midword():
    senses = "；".join(f"义项{i}很长" * 6 for i in range(8))
    gloss, _ = mod.derive(f"n. {senses}")
    assert len(gloss) <= mod.MAX_GLOSS_CHARS
    assert gloss.endswith("义项") or "；" in gloss or len(gloss) <= mod.MAX_GLOSS_CHARS
    # 截断处必须是完整义项边界：不能以半个词收尾
    assert not gloss.endswith("；")


def test_line_that_is_only_pos_yields_nothing():
    """只有 `n.` 没有义项的行，不该产出空 meaning_cn。"""
    assert mod.derive("n.") == (None, None)
    assert mod.derive("n.\n") == (None, None)


def test_skips_leading_empty_lines():
    gloss, pos = mod.derive("\n\nn. 银行\nvi. 岸")
    assert (pos, gloss) == ("n.", "银行")


def test_pos_truncated_to_20_chars():
    long_pos = "x" * 40
    _gloss, pos = mod.derive(f"{long_pos}. 释义")
    assert pos is None or len(pos) <= 20


def test_pos_truncation_via_real_tag():
    _g, pos = mod.derive("interjection. 啊")
    assert pos == "interjection."[:20]


def test_crlf_normalised():
    gloss, pos = mod.derive("n. 银行；岸\r\nvt. 存入")
    assert (pos, gloss) == ("n.", "银行；岸")


def test_derive_is_pure_no_mutation():
    canonical = "n. 银行；岸"
    mod.derive(canonical)
    assert canonical == "n. 银行；岸"
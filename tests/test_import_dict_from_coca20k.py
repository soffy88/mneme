"""COCA 20000 词表 → pos / 词典释义 导入器 + `TIER_DICTIONARY` 档位。

这些用例盯的是**实测踩到的三件事**：

1. 源文件的义项之间**没有空格**（`…终止n.放任…`），只能靠「汉字后紧跟词性标签」切；
   而 `a.m.`、`U.S.` 这类不能被误判成词性（要求标签后**紧跟汉字**）。
2. **必须留全部义项**，不能只取首个 —— 只取首个是本仓已知的坑
   （`blind`→百叶窗、`wet`→雨天，20 词人工审查抓出来的）。
3. **这个文件没有词频**：17,631 条是严格字母序，`water` 排在 17178。
   文件名里的 COCA 只说明词表出处。任何用它排频率的代码都是错的。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_dict_from_coca20k.py"
_spec = importlib.util.spec_from_file_location("coca20k", _SCRIPT)
assert _spec and _spec.loader
coca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coca)

from services import vocab_meaning as vm  # noqa: E402
from services import vocab_senses as vs  # noqa: E402


# --------------------------------------------------------------------------
# split_senses
# --------------------------------------------------------------------------


def test_splits_senses_that_have_no_space_between_them():
    got = coca.split_senses(
        "vt.放弃，抛弃,离弃，丢弃,使屈从,停止进行，终止n.放任，放纵,完全屈从于压制"
    )
    assert got == [
        ("vt", "放弃，抛弃,离弃，丢弃,使屈从,停止进行，终止"),
        ("n", "放任，放纵,完全屈从于压制"),
    ]


def test_keeps_every_sense_not_only_the_first():
    """只取首个义项是本仓已知的坑（`blind`→百叶窗）。"""
    got = coca.split_senses("n.附件,配饰,从犯adj.附加的,附属的,同谋的")
    assert [p for p, _ in got] == ["n", "adj"]
    assert got[1][1] == "附加的,附属的,同谋的"


def test_single_sense():
    assert coca.split_senses("adj.被放弃的，被遗弃的") == [
        ("adj", "被放弃的，被遗弃的")
    ]


def test_does_not_treat_abbreviation_as_pos():
    """`a.m.` / `U.S.` 不是词性 —— 判据要求词性标签后**紧跟汉字**。"""
    assert coca.split_senses("a.m. 上午") == []
    assert coca.split_senses("") == []
    assert coca.split_senses(None) == []


def test_pos_marker_without_following_chinese_is_not_a_sense():
    # `n.` 后面是 ASCII（不是释义）→ 不该切出一个空义项
    assert coca.split_senses("n. ") == []


# --------------------------------------------------------------------------
# pos / gloss 组装
# --------------------------------------------------------------------------


def test_primary_pos_is_the_first_senses_pos():
    assert coca.primary_pos(coca.split_senses("vt.保护n.保护物")) == "vt"
    assert coca.primary_pos([]) is None


def test_join_gloss_uses_newline_and_pos_label_per_line():
    """`services.vocab_senses.parse_senses` 按行解析、每行可带行首词性标签，
    所以写进去的形状必须和它读的一致，否则义项选择用不上。"""
    out = coca.join_gloss(coca.split_senses("vt.保护n.保护物"))
    assert out == "vt. 保护\nn. 保护物"


def test_join_gloss_shape_is_readable_by_parse_senses():
    senses = coca.split_senses(
        "n.附件,配饰,从犯adj.附加的,附属的,同谋的"
    )
    parsed = vs.parse_senses(coca.join_gloss(senses))
    assert [s.text for s in parsed] == ["附件,配饰,从犯", "附加的,附属的,同谋的"]
    # `canon_pos` 把 `n.` 归一为 `noun` —— 这条断言顺带验证了往返：
    # 我们写进去的形状，`parse_senses` 真能读回来并认出词性。
    assert [s.pos for s in parsed] == ["noun", "adj"]


def test_join_gloss_rejects_overlong_rather_than_silently_truncating():
    """截断会丢义项 —— 必须拒掉并让调用方看见，不能悄悄截。"""
    senses = [("n", "很长的释义" * 60)]
    assert coca.join_gloss(senses) is None
    assert len(coca.join_gloss([("n", "短")])) == len("n. 短")


def test_join_gloss_empty():
    assert coca.join_gloss([]) is None


# --------------------------------------------------------------------------
# TIER_DICTIONARY 的档位与音标防护
# --------------------------------------------------------------------------


def test_dictionary_tier_beats_derived_but_loses_to_canonical():
    """词典释义比「从单句模型派生」可靠，但仍不是教材原文（spec 要求教材优先）。"""
    only_dict = vm.classify_meaning_source(
        meaning_cn=None,
        canonical_meaning="[ˈeərən]",
        derived_gloss=None,
        dictionary_gloss="放弃；抛弃",
        dictionary_source="ECHOTYPE_COCA20000",
    )
    assert only_dict.tier == vm.TIER_DICTIONARY
    assert only_dict.usable

    # 教材原文优先
    assert vm.classify_meaning_source(
        meaning_cn="教材释义",
        canonical_meaning=None,
        dictionary_gloss="词典释义",
    ).tier == vm.TIER_CANONICAL

    # legacy（canonical_meaning 可用）也压过词典
    assert vm.classify_meaning_source(
        meaning_cn=None,
        canonical_meaning="vt. 保护，防卫；警戒",
        dictionary_gloss="词典释义",
    ).tier == vm.TIER_LEGACY


def test_dictionary_provenance_string_is_not_a_lying_one():
    """溯源串必须是真的。`vocabulary_derived_glosses` 的串被硬编码成
    「从真实语料句派生」，对词典来源那句话就是假的 —— 所以词典另起一档。"""
    v = vm.classify_meaning_source(
        meaning_cn=None,
        canonical_meaning=None,
        dictionary_gloss="放弃；抛弃",
        dictionary_source="ECHOTYPE_COCA20000",
    )
    assert v.source_column == "vocabulary_dictionary_glosses"
    assert "词典来源" in v.reason
    assert "ECHOTYPE_COCA20000" in v.reason
    assert "语料" not in v.reason, "不能把词典来源说成语料派生"


def test_dictionary_gloss_that_is_phonetic_is_rejected():
    """有出处**不能**免检音标污染 —— 这列是要给孩子背的。"""
    v = vm.classify_meaning_source(
        meaning_cn=None,
        canonical_meaning=None,
        dictionary_gloss="[ˈeərən]",
    )
    assert v.tier == vm.TIER_UNUSABLE
    assert not v.usable


def test_dictionary_tier_is_exported():
    assert "TIER_DICTIONARY" in vm.__all__

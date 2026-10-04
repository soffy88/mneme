"""「canonical_meaning 到底是释义还是读音」的判定契约 —— CME-P1.5。

为什么单独一个文件：教材词表把**音标**和**带方括号义项标签的释义**写进同一个
`canonical_meaning` 列，所以「以 `[（(` 开头」根本不能判定是音标。旧规则正是这么
判的，结果是**双向**出错：

- 真音标 `[ˈeərən]` 被拒 —— 这是对的；
- 但 `[法] 法案`、`[天] 十月`、`(使)远离，(使)不接近`、`[人名] 齐珀`、
  `（等于the United Kingdom）英国` 也被当成音标丢掉。实测**全表 11 条**至今
  `meaning_cn` 仍为空 —— 它们不是被正确拒绝，是被**误判**。

反向风险更致命：`meaning_cn` 是**直接给学生背**的字段，一旦音标混进去，
就是「把 [ˈeərən] 当成中文意思显示」。

下面每条样本都取自生产 `vocabulary_items`（2026-10-03 只读查询），不是编的。
"""

from __future__ import annotations

import pytest

from services.vocab_meaning import (
    KIND_GLOSS,
    KIND_MISSING,
    KIND_PHONETIC,
    KIND_PLACEHOLDER,
    TIER_CANONICAL,
    TIER_DERIVED,
    TIER_LEGACY,
    TIER_UNUSABLE,
    classify_canonical_meaning,
    classify_meaning_source,
    is_phonetic_transcription,
)

# ── 生产真样本：真音标（括号开头 + 内部无汉字）──────────────────────────────
REAL_PHONETICS = [
    "[ˈeərən]",
    "[ˌeɪ ˈsiː]",
    "[æfˈɡænɪstɑːn; æfˈɡænɪstæn]",
    "[ˈeərən]",
]

# ── 生产真样本：带方括号**义项/领域标签**的释义，曾被误判成音标 ──────────────
# 这些就是那 11 条的一部分。判成音标 = 学生的释义凭空消失。
REAL_LABELLED_GLOSSES = [
    ("zipper", "[人名] 齐珀"),
    ("whitcomb", "[人名] [英格兰人姓氏] 惠特科姆 Whitcombe的变体"),
    ("bill", "[法] 法案；广告；账单；[金融] 票据；钞票；清单"),
    ("october", "[天] 十月"),
    ("bit", "[计] 比特（二进位制信息单位）；少量；马嚼子；辅币；老一套；一点，一块"),
    ("bookcase", "[家具] 书柜，书架"),
    ("energy", "[物] 能量；精力；活力；精神"),
    ("divide", "[地理] 分水岭，分水线"),
    ("spider-man", "[电影]蜘蛛侠"),
    ("keep ... away from", "(使)远离，(使)不接近；(使)不在"),
    ("come on", "(演员)出台；进行(很好)；(暴风雨等)起；(病,苦痛等)加深"),
    ("come true", "(预言等)成事实；实现；(作物)不变种地发芽生长"),
    ("corn", "（美）玉米；（英）谷物；[皮肤] 鸡眼"),
    ("the uk", "（等于the United Kingdom）英国"),
    ("won't", "[澳大利亚、新西兰口语]厌恶；不能容忍；= will not"),
    ("here is", "[口语]；我们(或你，你们)到了!；这就是我们(或你，你们)所要的东西。"),
    ("see you!", "[口语]再见!"),
    ("say cheese", "（摄影者鼓励被拍者笑时说的）笑一笑"),
    ("what is", "[计] whatis命令"),
    ("x-irradiation", "[医]X线辐照"),
]


@pytest.mark.parametrize("ipa", REAL_PHONETICS)
def test_real_phonetics_are_not_glosses(ipa):
    assert is_phonetic_transcription(ipa) is True
    v = classify_canonical_meaning(ipa)
    assert v.kind == KIND_PHONETIC
    assert v.tier == TIER_UNUSABLE
    assert v.gloss is None, "音标绝不能当释义返回"


@pytest.mark.parametrize("word,gloss", REAL_LABELLED_GLOSSES)
def test_labelled_glosses_are_not_mistaken_for_phonetics(word, gloss):
    """**这条是本文件的核心。** 旧规则会把它们全判成音标。

    变异验证：把 `is_phonetic_transcription` 改回 `^[\\[（(]` → 本测试 20 条全败。
    """
    assert is_phonetic_transcription(gloss) is False, f"{word}: {gloss!r} 被误判成音标"
    v = classify_canonical_meaning(gloss)
    assert v.kind == KIND_GLOSS
    assert v.tier == TIER_LEGACY
    assert v.gloss == gloss


def test_meaning_source_prefers_meaning_cn_as_canonical():
    v = classify_meaning_source(meaning_cn="放弃；抛弃", canonical_meaning="[ˈeərən]")
    assert v.tier == TIER_CANONICAL
    assert v.source_column == "meaning_cn"
    assert v.gloss == "放弃；抛弃"


def test_meaning_source_falls_back_to_legacy_canonical():
    v = classify_meaning_source(meaning_cn=None, canonical_meaning="vt. 保护，防卫；警戒")
    assert v.tier == TIER_LEGACY
    assert v.source_column == "canonical_meaning"
    assert v.gloss == "vt. 保护，防卫；警戒"


def test_meaning_source_never_returns_a_phonetic():
    """meaning_cn 与 canonical_meaning 都是音标 → 判无可用释义，**不给**读音。"""
    v = classify_meaning_source(meaning_cn=None, canonical_meaning="[æbændən]")
    assert v.tier == TIER_UNUSABLE
    assert v.gloss is None
    assert v.kind == KIND_PHONETIC


def test_polluted_meaning_cn_is_refused_even_though_column_is_authoritative():
    """meaning_cn 自身被污染时必须拒用（实测全表 0 条，但这是给学生看的字段）。

    这条是防御性的：宁可判成「无可用释义」也不能把音标当中文意思显示出去。
    """
    v = classify_meaning_source(meaning_cn="[ˈeərən]", canonical_meaning="放弃")
    assert v.tier == TIER_UNUSABLE
    assert v.gloss is None
    assert "污染" in v.reason


def test_exact_phonetic_marker_is_refused_without_killing_similar_glosses():
    """括号里**整体只是**音标标记词 → 判读音。

    第一版这里写的是「包含标记词 + 限长 6 字符」，但变异验证发现：把长度限制删掉，
    41 项测试**全绿** —— 说明那个分支根本没被测到，它防的是一个生产里不存在的场景
    （实测 0 行 `（音标）` 标记）。改成精确匹配后意图才可被测。
    """
    for marker in ["（音标）", "（读音）", "[发音]", "(phonetic)", "（IPA）"]:
        assert is_phonetic_transcription(marker) is True, marker

    # 「含标记词但不是整体等于」→ 都是正常释义，必须保住。
    for gloss in [
        "n. 发音；读法",          # 「发音」一词自己的释义（生产里确有此行）
        "vi. 发音；",
        "[发音]辨音",
        "(动词)发音",
    ]:
        assert is_phonetic_transcription(gloss) is False, gloss


@pytest.mark.parametrize("ph", ["", "  ", "无", "-", "—", "/", "N/A", "null", None])
def test_placeholders_are_unusable(ph):
    v = classify_canonical_meaning(ph)
    assert v.kind in (KIND_PLACEHOLDER, KIND_MISSING)
    assert v.tier == TIER_UNUSABLE
    assert v.gloss is None


def test_empty_is_missing_not_placeholder():
    assert classify_canonical_meaning("").kind == KIND_MISSING
    assert classify_canonical_meaning(None).kind == KIND_MISSING
    assert classify_canonical_meaning("无").kind == KIND_PLACEHOLDER


def test_derivation_script_shares_the_same_decision():
    """`derive_meaning_from_canonical.derive()` 必须与本模块给出同一判定。

    两个互相矛盾的判定正是单源红线要防的漂移 —— 所以直接断言它们一致。
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "derive_meaning_from_canonical.py"
    )
    spec = importlib.util.spec_from_file_location("derive_mfc", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    probes = [g for _w, g in REAL_LABELLED_GLOSSES] + REAL_PHONETICS + ["（音标）"]
    for probe in probes:
        derived_gloss, _pos = mod.derive(probe)
        assert (derived_gloss is None) == is_phonetic_transcription(probe), probe


def test_verdict_payload_is_serialisable():
    import json

    v = classify_meaning_source(meaning_cn="放弃", canonical_meaning=None)
    assert json.loads(json.dumps(v.to_payload()))["tier"] == TIER_CANONICAL

# ── derived_from_corpus 档（CME-P1.12）─────────────────────────────────────
# 461 个核心单词有 NCE 真实句但没有中文释义，其中 459 个 canonical 是纯音标 →
# 确定性派生走不通。用既有 oprim 从**真实例句**派生，存独立表
# vocabulary_derived_glosses（alembic d7e8f9a0b1c2），出处显式可回溯。


def test_canonical_wins_over_derived():
    v = classify_meaning_source(
        meaning_cn="放弃；抛弃", canonical_meaning="vt. 放弃", derived_gloss="弃绝"
    )
    assert v.tier == TIER_CANONICAL
    assert v.gloss == "放弃；抛弃"


def test_legacy_wins_over_derived():
    """canonical_meaning 能给出释义时优先用它 —— 它是教材原文，比派生更权威。"""
    v = classify_meaning_source(
        meaning_cn=None, canonical_meaning="vt. 保护，防卫", derived_gloss="守卫"
    )
    assert v.tier == TIER_LEGACY
    assert v.gloss == "vt. 保护，防卫"


def test_derived_used_when_textbook_columns_are_phonetics():
    """`diet` 的真实库内状态：meaning_cn 空、canonical 是 `[ˈdaɪət]`。"""
    v = classify_meaning_source(
        meaning_cn=None, canonical_meaning="[ˈdaɪət]", derived_gloss="饮食；节食"
    )
    assert v.tier == TIER_DERIVED
    assert v.kind == KIND_GLOSS
    assert v.gloss == "饮食；节食"
    assert v.source_column == "vocabulary_derived_glosses"


def test_derived_is_still_unusable_when_absent():
    v = classify_meaning_source(meaning_cn=None, canonical_meaning="[ˈdaɪət]")
    assert v.tier == TIER_UNUSABLE
    assert v.gloss is None


def test_derived_gloss_itself_checked_for_phonetic_pollution():
    """派生列也可能被污染 —— 同样要挡住，不能因为「有出处」就免检。"""
    v = classify_meaning_source(
        meaning_cn=None, canonical_meaning="[ˈdaɪət]", derived_gloss="[ˈdaɪət]"
    )
    assert v.usable is False

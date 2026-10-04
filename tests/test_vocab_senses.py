"""义项还原与「主义项」选择的回归测试（CME-P1.6）。

核心事实（2026-10-03 实测）：`vocabulary_items.canonical_meaning` 存的是教材词表的
**完整多义项**，但 `meaning_cn` 常常只截了第一个 —— 于是

    blind → 掩饰，借口；百叶窗   （漏掉 adj. 盲目的；瞎的）
    wet   → 雨天；湿气           （漏掉 adj. 潮湿的；有雨的）
    fine  → 罚款                （漏掉 adj. 好的；优良的）

学生于是记住冷门义项，而记忆画面就是照着这个义项生成的。

下面的 `canonical_meaning` 全部取自生产真实行。
"""

from __future__ import annotations

from services.vocab_senses import canon_pos, parse_senses, select_primary_sense

# ── 生产真实 canonical_meaning ──────────────────────────────────────────────
REAL = {
    "blind": (
        "adj",
        "n. 掩饰，借口；百叶窗\nadj. 盲目的；瞎的\nvt. 使失明；使失去理智\nadv. 盲目地；看不见地",
        "adj",
        "盲目的；瞎的",
    ),
    "wet": (
        "adj",
        "n. 雨天；湿气\nadj. [气象][物] 潮湿的；有雨的\nvt. 弄湿\nvi. 变湿",
        "adj",
        "潮湿的；有雨的",
    ),
    "fine": (
        "adj",
        "n. 罚款\nadj. 好的；优良的\nvt. 罚款；处以罚款",
        "adj",
        "好的；优良的",
    ),
    "bed": ("n", "n. 床；基础；河底，海底", "noun", "床；基础；河底，海底"),
    "advice": ("n", "n. 建议；忠告；劝告；通知", "noun", "建议；忠告；劝告；通知"),
}


def test_pos_column_selects_the_right_sense_for_polysemous_words():
    """三例全部命中 —— 这正是 20 词人工审查里判「记忆锚在冷门义项」的那三个词。"""
    for word, (pos, canonical, want_pos, want_text) in REAL.items():
        sense, _reason = select_primary_sense(canonical, pos)
        assert sense is not None, word
        assert sense.pos == want_pos, (word, sense.pos, sense.pos)
        assert sense.text == want_text, (word, sense.text)


def test_continuous_sense_tags_are_all_stripped():
    """`[气象][物] 潮湿的` 有两个连续标签，第一版只剥掉一个，漏了 `[物]`。"""
    sense, _ = select_primary_sense(REAL["wet"][1], "adj")
    assert sense.text == "潮湿的；有雨的"


def test_phonetic_canonical_yields_no_senses():
    """音标不是义项（canonical_meaning 里混着 9,844 条真音标）。

    判定复用 services.vocab_meaning 的唯一源 —— 这里验证**组合生效**。
    """
    for ipa in ("[ˈtaɪt(ə)l", "[ˈeərən]", "[æfˈɡænɪstɑːn]"):
        assert parse_senses(ipa) == []
        sense, reason = select_primary_sense(ipa, None)
        assert sense is None, ipa
        assert "没有可用义项" in reason


def test_pos_empty_falls_back_to_first_sense():
    sense, reason = select_primary_sense("n. 头衔；职称\nn. 标题", None)
    assert sense.text == "头衔；职称"
    assert "pos 列为空" in reason


def test_pos_not_matching_any_sense_falls_back_but_says_so():
    """词性对不上要兜底，但**必须在理由里说明**，否则读日志的人以为选对了。"""
    canonical = "n. 头部\nadj. 首位的"
    sense, reason = select_primary_sense(canonical, "prep")
    assert sense.text == "头部"
    assert "兜底" in reason


def test_no_senses_when_only_placeholders():
    assert parse_senses("") == []
    assert parse_senses(None) == []
    assert parse_senses("无\n-\n—") == []


def test_sense_without_pos_label_is_kept():
    """教材表里确实有无词性标签的义项行，不能丢。"""
    senses = parse_senses("银行；账户\n岸")
    assert [s.text for s in senses] == ["银行；账户", "岸"]
    assert all(s.pos is None for s in senses)


def test_canon_pos_aliases():
    assert canon_pos("n.") == "noun"
    assert canon_pos("adj") == "adj"
    assert canon_pos("a") == "adj"          # 中文教材缩写
    assert canon_pos("ad") == "adv"         # 中文教材缩写
    assert canon_pos("vt.") == "verb"
    assert canon_pos("vi.") == "verb"
    assert canon_pos("link v.") == "verb"
    assert canon_pos("v & n") == "verb"     # pos 列里就有这种写法
    assert canon_pos(None) is None
    assert canon_pos("") is None

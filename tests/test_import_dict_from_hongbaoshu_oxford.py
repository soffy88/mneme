"""EchoType 红宝书 / 牛津5000 → pos / 词典释义 导入器。

这些用例盯的是**实测踩到的东西**，每条都对应源文件里的真实样本：

1. `hongbaoshu` 的词性组在**句尾**，且 277 条是**多词性**（`access: 进入， 访问 (noun, vt.)`）。
2. `oxford5000` 的 `adv.` 被 PDF 抽取**截断成 `ad` + `v.`**（371 条）—— 若按行首词性
   标签解析会把 `abroad` 标成**动词**。必须**拒绝**而不是猜（实测打开修复只多拿
   22 条释义，收益远小于给孩子看错词性的风险）。
3. `oxford5000` 尾部有派生词表段（`时态:abandoned…`），那是**删除非释义内容**，
   与「拒绝」不同 —— 它该被截掉，不该让整条释义作废。
4. 与第一批 `coca20000` 同一口径：**只填当前完全拿不到释义的词**，不覆盖已有的。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "import_dict_from_hongbaoshu_oxford.py"
)
_spec = importlib.util.spec_from_file_location("hb_ox", _SCRIPT)
assert _spec and _spec.loader
hbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hbox)

from services import vocab_senses as vs  # noqa: E402


# --------------------------------------------------------------------------
# hongbaoshu：词性组在句尾
# --------------------------------------------------------------------------


def test_hongbaoshu_pos_group_at_end_is_parsed():
    """实测样本：`放弃， 放置不管 (vt.)`"""
    assert hbox.parse_hongbaoshu("放弃， 放置不管 (vt.)") == ("vt", "放弃， 放置不管")


def test_hongbaoshu_multi_pos_takes_first_not_guessing():
    """`access: 进入， 访问 (noun, vt.)` —— 多词性取第一个（词表已按义项排序）。"""
    got = hbox.parse_hongbaoshu("进入， 访问 (noun, vt.)")
    assert got is not None
    assert got[0] == "n"


def test_hongbaoshu_pos_group_not_at_end_still_parses():
    """实测样本：`艺术 (n.) - 创造性表现` —— 词性组后跟 ` - ` 说明段。"""
    got = hbox.parse_hongbaoshu("艺术 (n.) - 创造性表现")
    assert got is not None
    assert got[0] == "n"
    assert got[1] == "艺术"


def test_hongbaoshu_slash_separated_pos_takes_first():
    """实测样本：`广播 (n./vt.) - 广播节目` —— 斜杠并列词性。"""
    got = hbox.parse_hongbaoshu("广播 (n./vt.) - 广播节目")
    assert got is not None
    assert got[0] == "n"


def test_hongbaoshu_two_paren_groups_is_rejected():
    """形状认不就别猜 —— 组不恰好一个就拒。"""
    assert hbox.parse_hongbaoshu("艺术 (n.) (vt.)") is None


def test_hongbaoshu_trailing_junk_after_pos_group_is_rejected():
    """组后不是句尾也不是 ` - ` 说明段 → 拒（不截断、不清洗）。"""
    assert hbox.parse_hongbaoshu("放弃 (vt.) 时态:abandoned") is None


def test_hongbaoshu_pos_synonyms_are_normalised():
    """长写法归一到本仓 pos 词表，否则下游 `canon_pos` 认不出。"""
    assert hbox.parse_hongbaoshu("任何人 (pronoun)") == ("pron", "任何人")
    assert hbox.parse_hongbaoshu("能够，可能 (modal verb)") == ("aux", "能够，可能")
    # 「复数名词」确定是名词 —— 归一，而不是丢弃整条释义
    assert hbox.parse_hongbaoshu("衣服 (plural noun)") == ("n", "衣服")


def test_hongbaoshu_unknown_pos_token_rejects_whole_entry():
    """认不出的词性 → 整条拒。写一个可能错的 pos 比不写更糟。"""
    assert hbox.parse_hongbaoshu("甜的 (adj., qq)") is None


def test_hongbaoshu_without_pos_group_is_rejected_not_guessed():
    """没有 `(pos)` 组 = 这份词表在该条上没有可靠词性，不能瞎猜。"""
    assert hbox.parse_hongbaoshu("放弃， 遗弃") is None
    assert hbox.parse_hongbaoshu("") is None
    assert hbox.parse_hongbaoshu(None) is None


def test_hongbaoshu_gloss_without_chinese_is_rejected():
    """无汉字的释义对判 `MEANING_AUTHORITY` 没有帮助。"""
    assert hbox.parse_hongbaoshu("to give up (vt.)") is None


# --------------------------------------------------------------------------
# oxford5000：截断的 adv. 必须拒绝
# --------------------------------------------------------------------------


def test_oxford_truncated_adv_is_rejected_not_parsed_as_verb():
    """实测样本：`abroad: ad; v. 到国外, 在国外到处`。

    `adv.` 被抽取器在句点处切坏成 `ad` + `v.`。若不拦，这里会返回
    `[("v", "到国外…")]` —— 把一个纯副词标成**动词**。
    """
    assert hbox.parse_oxford5000("ad; v. 到国外, 在国外到处, 广泛流传在户外") is None
    assert hbox.parse_oxford5000("ad; v. 几乎，差不多，差一点") is None
    assert hbox.parse_oxford5000("ad, v. 实际 上") is None


def test_oxford_intact_adv_is_parsed_as_adverb():
    """对照组：没被截断的 `adv.` 必须正常解析（否则上面的拒绝会连累正常词）。"""
    got = hbox.parse_oxford5000("adv. 迅速地；很快地")
    assert got == [("adv", "迅速地；很快地")]


def test_oxford_multi_sense_keeps_every_sense():
    """只取首个义项是本仓已知的坑（`blind`→百叶窗）。"""
    got = hbox.parse_oxford5000(
        "v. （不顾责任、义务等）离弃，遗弃，抛弃; n. 【正式】放任；放纵"
    )
    assert got is not None
    assert [p for p, _ in got] == ["v", "n"]
    assert got[1][1] == "【正式】放任；放纵"


def test_oxford_truncates_inflection_tail_but_keeps_senses():
    """`时态:` 之后是派生词表，**不是义项** —— 该截掉。

    这是「删除非释义内容」，与拒绝截断 `adv.` 是两码事：截掉后释义仍可用。
    """
    got = hbox.parse_oxford5000(
        "n. 滥用；辱骂；虐待; vt. 滥用；辱骂；虐待; 时态:abused, abusing, abuses名 词:abuser"
    )
    assert got is not None
    assert [p for p, _ in got] == ["n", "vt"]
    assert all("时态" not in g and "abuser" not in g for _, g in got)


def test_oxford_rejects_extractor_junk_and_posless():
    assert hbox.parse_oxford5000(
        "add-on1 ENTRIES FOUND:add-on (noun)add-on/ˈædˌɑːn/ nounplural add-ons"
    ) is None
    # 短语（无词性标签）—— 本仓口径只吃单词，这类直接拒
    assert hbox.parse_oxford5000("对…负有责任；对…做出解释") is None
    assert hbox.parse_oxford5000("") is None
    assert hbox.parse_oxford5000(None) is None


# --------------------------------------------------------------------------
# gloss 组装：与 parse_senses 往返
# --------------------------------------------------------------------------


def test_join_gloss_roundtrips_through_parse_senses():
    """写进去的形状必须 `services.vocab_senses.parse_senses` 真能读回来。"""
    senses = hbox.parse_oxford5000("v. 离弃，遗弃; n. 放任；放纵")
    assert senses is not None
    parsed = vs.parse_senses(hbox.join_gloss(senses))
    assert [s.pos for s in parsed] == ["verb", "noun"]
    assert [s.text for s in parsed] == ["离弃，遗弃", "放任；放纵"]


def test_join_gloss_rejects_overlong_rather_than_truncating():
    """截断会丢义项 —— 必须拒掉并让调用方看见。"""
    assert hbox.join_gloss([("n", "很长的释义" * 60)]) is None
    assert hbox.join_gloss([("n", "短")]) == "n. 短"
    assert hbox.join_gloss([]) is None


def test_primary_pos_is_first_sense():
    assert hbox.primary_pos([("vt", "保护"), ("n", "保护物")]) == "vt"
    assert hbox.primary_pos([]) is None


def test_parse_entry_routes_by_source_tag():
    assert hbox.parse_entry("ECHOTYPE_HONGBAOSHU", "放弃， 放置不管 (vt.)") == (
        "vt",
        "vt. 放弃， 放置不管",
    )
    assert hbox.parse_entry("ECHOTYPE_OXFORD5000", "adv. 迅速地") == (
        "adv",
        "adv. 迅速地",
    )
    assert hbox.parse_entry("ECHOTYPE_OXFORD5000", "ad; v. 到国外") == (None, None)


# --------------------------------------------------------------------------
# load_entries：重复词先出现者胜
# --------------------------------------------------------------------------


def test_load_entries_keeps_first_occurrence(tmp_path):
    """同文件内重复词不覆盖 —— 后段噪声不该改写已解析出的释义。"""
    import json

    src = tmp_path / "dup.json"
    src.write_text(
        json.dumps(
            [
                {"word": "abandon", "sentence": "放弃， 遗弃 (vt.)"},
                {"word": "abandon", "sentence": "乱写的东西 (zzz.)"},
            ]
        ),
        encoding="utf-8",
    )
    got, rejects = hbox.load_entries(src, "ECHOTYPE_HONGBAOSHU", None)
    assert got["abandon"]["pos"] == "vt"
    assert rejects["dup_word"] == 1

# --------------------------------------------------------------------------
# 复合词性 `vt. & vi.` 与源数据粘接的百科尾巴
# --------------------------------------------------------------------------


def test_oxford_compound_pos_ampersand_is_stripped_from_gloss():
    """实测样本：`vt. & vi. (使)联合` —— `& vi.` 是词性的一部分，不是释义。

    不剥掉的话义项前会多出「& vi.」，写进 `gloss` 就成了给孩子看的噪声。
    """
    got = hbox.parse_oxford5000("vt. & vi. (使)联合")
    assert got == [("vt", "(使)联合")]


def test_oxford_rejects_english_glued_into_chinese_gloss():
    """实测样本：`vi. 保持平衡；相称；抵销Balance天秤星座`。

    `Balance天秤星座` 是百科尾巴粘上来的，不是义项。整条拒（实测 5 条）。
    """
    assert hbox.parse_oxford5000(
        "vi. 保持平衡；相称；抵销Balance天秤星座"
    ) is None
    assert hbox.parse_oxford5000(
        "vt. 追逐；追捕；试图赢得; vi. 追赶; n. 追击Chase蔡斯(姓氏)"
    ) is None


def test_oxford_keeps_clean_gloss_with_latin_inside_parentheses():
    """对照组：括号里的英文**说明**是合法内容，不该被粘接检测误杀。

    `代替Miss或Mrs的字` 前后都有汉字，若检测写成「含 ASCII 即拒」就会误杀。
    """
    got = hbox.parse_oxford5000("n. 女士(代替Miss或Mrs的字，不指明称呼人的婚姻状况)")
    assert got is not None
    assert "Miss" in got[0][1]


def test_oxford_rejects_mid_string_truncated_adv():
    """实测样本：`adj. 第七的；七分之一的ad\\nv. 居第七位地` —— 行首那条拦不住它。"""
    assert hbox.parse_oxford5000("n. 第七；七分之一\nadj. 第七的；七分之一的ad\nv. 居第七位地") is None
    # 完整的 adv. 不能被误杀
    assert hbox.parse_oxford5000("adj. 奇怪的； adv. 奇怪地") is not None


def test_oxford_truncates_derived_word_metadata_tail():
    """实测写法很杂：`动 词:` / `复 数:` / `名 词:` —— 都按「词 + 冒号」收。"""
    got = hbox.parse_oxford5000("n. 摩托车动 词:motorcycle")
    assert got == [("n", "摩托车")]
    got = hbox.parse_oxford5000("n. 孙(女), 外孙(女)复 数: grandchildren")
    assert got == [("n", "孙(女), 外孙(女)")]


def test_oxford_rejects_long_latin_tail_glued_into_gloss():
    """实测样本：`回形针CLIPabbr. Cellular Logic Image Processor 单元逻辑映象处理器…`

    上一条粘接检测盖不住这种「英文后跟标点而非汉字」的情况，故再加一条长串英文检测。
    """
    assert hbox.parse_oxford5000(
        "n. 夹子；修剪；回形针CLIPabbr. Cellular Logic Image Processor 单元逻辑映象处理器Compiler Language"
    ) is None

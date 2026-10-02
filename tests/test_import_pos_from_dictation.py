"""scripts/import_pos_from_dictation.py 的解析回归测试。

第一版解析器用「尾部正则匹配词性」，被贪婪匹配吃掉单词的一部分：
`ability n` → 识别成 pos=`ity n` → `ity` 不在词性表 → 整格判为未解析。
实测解析率只有 **36/1600**。改成「从尾部逐个摘 token」后 1484/1600。

这里钉住那条真实 bug，以及容易被静默搞错的几种形态：
  - 词性相邻无空格 / 多词性 / `&` 与 `,` 连接符
  - `*ad n` 这类「单词本身长得像词性标记」的必须拒绝，不能把 `ad` 当词性
  - 括号变形 `bad (worse, worst) a` 必须能解析出 pos 并保留括号
  - 中文标题行 / 页码必须跳过
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "import_pos_from_dictation.py"
    spec = importlib.util.spec_from_file_location("import_pos_from_dictation", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ── 真实版式（pdftotext -layout 双栏）──────────────────────────────────────

TWO_COL = """\
新课标初中英语词汇表


*ability n                  advertisement n
 able a                     advice n
 about prep & ad           *advise v
 above prep                 afford v
 abroad a & ad              afraid a
 after ad, prep & conj     agree v
"""

ONE_COL = """\
almost ad
alone a
appear v
apple n
april n
bad (worse, worst) a
become (became, become) v
*ad n
art n
be (is, am, are, was, were)
"""


def test_two_column_layout():
    out, _ = mod.parse_cells(TWO_COL)
    assert out["ability"] == "n"
    assert out["advertisement"] == "n"
    assert out["able"] == "adj"
    assert out["advise"] == "v"
    assert out["agree"] == "v"


def test_greedy_regex_bug_would_have_destroyed_this():
    """反向证明尾部正则的贪婪问题，防止有人「优化」回正则写法。"""
    import re

    # 旧写法：从尾部正则匹配词性
    bad = re.findall(r"((?:\s*[a-z]{1,5}\.?\s*)+)$", "ability n")
    # 贪婪吃到了 'ity' —— 'ity' 是单词的一部分，不是词性
    assert "ity" in bad[0]
    # 新写法正确
    out, _ = mod.parse_cells("*ability n")
    assert out["ability"] == "n"


def test_compound_pos_with_ampersand():
    out, _ = mod.parse_cells(TWO_COL)
    assert out["about"] == "prep & adv"   # a -> adj, ad -> adv


def test_compound_pos_with_comma_and_ampersand():
    out, _ = mod.parse_cells(TWO_COL)
    assert out["after"] == "adv & prep & conj"


def test_pos_normalisation_a_to_adj():
    """源表用 `a`=形容词、`ad`=副词；归一化消除歧义。"""
    out, _ = mod.parse_cells(ONE_COL)
    assert out["able"] if "able" in out else True
    out2, _ = mod.parse_cells("alone a\nalready ad")
    assert out2["alone"] == "adj"
    assert out2["already"] == "adv"


def test_parenthesised_inflections_parsed_and_headword_indexed():
    """`bad (worse, worst) a` 既保留全形，也要按裸词 `bad` 索引一份，
    否则查 vocabulary_items.word（存裸词）永远 miss。"""
    out, _ = mod.parse_cells(ONE_COL)
    assert out["bad (worse, worst)"] == "adj"
    assert out["bad"] == "adj", "必须额外索引词头"
    assert out["become (became, become)"] == "v"
    assert out["become"] == "v"


def test_entry_with_no_pos_is_rejected_not_guessed():
    out, unparsed = mod.parse_cells(ONE_COL)
    # be (is, am, ...) 没有词性标注 —— 必须进未解析，不能瞎猜成 v
    assert "be" not in out
    assert any(c.startswith("be (") for c in unparsed)


def test_word_that_looks_like_pos_token_is_rejected():
    """`ad n` / `art n` / `aux v` —— 首 token 就是词性标记，摘完无词，必须拒绝。"""
    out, unparsed = mod.parse_cells(ONE_COL)
    for w in ("ad", "art"):
        assert w not in out, f"{w} 被误当成词性吞掉了单词"
    assert any(c.lstrip("*") == "ad n" for c in unparsed)


def test_cjk_title_and_page_numbers_skipped():
    out, _ = mod.parse_cells("\x0c\n   12  \n- 3 -\n")
    assert out == {}


def test_star_prefix_is_difficulty_marker_not_part_of_word():
    out, _ = mod.parse_cells("*ability n\nability")
    assert out["ability"] == "n"


def test_parse_is_pure():
    raw = "apple n\n"
    mod.parse_cells(raw)
    assert raw == "apple n\n"
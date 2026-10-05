"""中考教辅 PDF → vocabulary_collocations 导入器。

这些用例盯的是**实测踩到的版面问题**，不是接口形状：

1. 版面是「N 行英文 → N 行中文」两列，**行数不等就整块丢掉** —— 不等说明串版了，
   硬配对会产出「英文词条挂到别人的中文释义」这种静默错数据。
2. **故事标题混在同一批版面里**（`A Young Officer and an Old Soldier`），靠
   「≥2 个词首大写」区分；而 `an astronaut`（1 个）、`a bank account`（0 个）
   必须**不被**误杀。
3. **语法句型混进来**（`not only...but also...`），靠含 `...` 排除。
4. 中文格有 **OCR 前导点**（`.送礼`、`.去海滩`），要只清首尾、保留中间的省略号。
5. 中心词挂错比不挂更糟 —— 查不到就丢弃并**记进报告**，不硬挂。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "import_collocations_from_k12.py"
)
_spec = importlib.util.spec_from_file_location("k12_coll", _SCRIPT)
assert _spec and _spec.loader
k12 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k12)


# --------------------------------------------------------------------------
# 版面配对
# --------------------------------------------------------------------------


def test_extract_pairs_zips_english_block_with_chinese_block(monkeypatch, tmp_path):
    lines = ["look in", "look around", "查看", "环顾", "DAY 1"]
    # 只把 PDF 读取替换掉；配对逻辑本身是真跑的
    class _Doc:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter([_Page("\n".join(lines))])

    class _Page:
        def __init__(self, t):
            self._t = t

        def get_text(self):
            return self._t

    import pymupdf

    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: _Doc())
    out = k12.extract_pairs(tmp_path / "x.pdf")
    assert ("look in", "查看") in out
    assert ("look around", "环顾") in out


def test_extract_pairs_drops_block_when_line_counts_differ(monkeypatch, tmp_path):
    """行数不等 → 整块丢。硬 zip 会把英文词挂到别人的中文释义上。"""
    lines = ["look in", "look around", "at last", "查看"]  # 3 英文 vs 1 中文

    class _Page:
        def get_text(self):
            return "\n".join(lines)

    class _Doc:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter([_Page()])

    import pymupdf

    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: _Doc())
    assert k12.extract_pairs(tmp_path / "x.pdf") == []


# --------------------------------------------------------------------------
# usable_phrase：四条排除规则
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "en",
    [
        "new adj.",  # 词表行，不是搭配
        "whether conj.",
        "/v. 电话",  # OCR 把词性挪进同一格
        "not only...but also...",  # 语法句型
        "A Young Officer and an Old Soldier",  # 故事标题（多个大写词）
        "day",  # 单词
        "one two three four five six seven eight nine",  # 超长
    ],
)
def test_usable_phrase_rejects_non_phrase_rows(en):
    assert k12.usable_phrase(en, "中文") is None, en


@pytest.mark.parametrize(
    ("en", "zh"),
    [
        ("an astronaut", "一名宇航员"),  # 只有首词大写 → 必须留
        ("a bank account", "银行账户"),  # 全小写 → 必须留
        ("alarm clock", "闹钟"),
    ],
)
def test_usable_phrase_keeps_real_phrases(en, zh):
    assert k12.usable_phrase(en, zh) is not None


def test_usable_phrase_strips_ocr_leading_dot_but_keeps_inner_ellipsis():
    """只清**首尾**的点：版面把页码/项目符号漏进了中文格（`.送礼`、`.去海滩`）。

    中间的 `......` 是原文的省略号，必须留着 —— 那是释义的一部分。
    """
    assert k12.usable_phrase("give a gift", ".送礼") == "give a gift"
    assert k12.usable_phrase("worry about", "对......担心") == "worry about"


def test_usable_phrase_drops_entry_when_only_dots_remain_after_clean():
    assert k12.usable_phrase("give a gift", "...") is None


# --------------------------------------------------------------------------
# 中心词判定
# --------------------------------------------------------------------------

_VOCAB = {"look": "v-look", "moment": "v-moment", "last": "v-last", "speak": "v-speak"}


def test_pick_head_prefers_last_content_word():
    """照既有 66 行的惯例：`traffic accident` → `accident`（末词）。"""
    vocab = {"accident": "id-acc", "traffic": "id-traf"}
    assert k12.pick_head("traffic accident", vocab) == "id-acc"


def test_pick_head_falls_back_to_first_when_last_is_a_stopword():
    assert k12.pick_head("look in", _VOCAB) == "v-look"
    assert k12.pick_head("wait a moment", _VOCAB) == "v-moment"


def test_pick_head_falls_back_to_first_when_last_word_is_absent_from_vocab():
    """末词**不在词表**时必须回退到首词。

    这条是「回退」逻辑唯一真正被走到的用例：上面那个用例里 `look in` 的末词
    已被 stopword 吃掉、`wait a moment` 的末词 `moment` 又恰好在词表里，
    所以只取末词也能过 —— 改实现不会被发现。这里让末词彻底查不到。
    """
    # 只有 `go` 在词表里，`abroad` 不在
    assert k12.pick_head("go abroad", {"go": "id-go"}) == "id-go"
    # 末词与首词都在时，仍然优先末词（既有 66 行的惯例）
    assert k12.pick_head("traffic accident", {"traffic": "t", "accident": "a"}) == "a"
    # 首词也不在 → 丢弃
    assert k12.pick_head("go abroad", {}) is None


def test_pick_head_ignores_placeholders():
    assert k12.pick_head("speak to sb.", _VOCAB) == "v-speak"


def test_pick_head_returns_none_when_nothing_matches():
    """查不到中心词就返回 None —— 由调用方丢弃并记录，不硬挂到虚词上。"""
    assert k12.pick_head("at last", {}) is None
    assert k12.pick_head("give a gift", {}) is None


def test_content_tokens_drops_stopwords_and_placeholders():
    assert k12.content_tokens("look in") == ["look"]
    assert k12.content_tokens("speak to sb.") == ["speak"]
    assert k12.content_tokens("have to") == []
    assert k12.content_tokens("one of...") == []
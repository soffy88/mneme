"""OPD 主题锚点解析器的回归测试。

存在的理由不只是「测对」：本文件同时**钉住一个负面结论** ——
《牛津图解词典》第三版**解决不了义项对齐问题**（见最后一组测试与 spec）。
解析器保留下来是因为它是一次**可复现的测量工具**：当初的判断依据是
「实测覆盖 36.3%」，后来发现那是含噪声的高估，真实值 13.4%。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "parse_opd_topic_anchors.py"
    spec = importlib.util.spec_from_file_location("parse_opd_topic_anchors", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# ── 版面解析（页面文本片段取自生产 PDF）───────────────────────────────────

def test_extracts_numbered_entries_and_skips_sentences():
    page = (
        "54\n"
        "A Kitchen\n"
        "1. cabinet\n"
        "2. shelf\n"
        "3. paper towels\n"
        "Ways to talk about location using on and in\n"
        "Use on for the counter, shelf, burner, stove, and\n"
    )
    words = mod.extract_page_entries(page)
    assert "cabinet" in words and "shelf" in words and "paper towels" in words
    # 例句没有编号，不该被当成词条
    assert not any("counter" in w for w in words)


def test_reads_topic_label():
    """取**更具体的面板名**：页面上 `Colors`（大类）是分类标题，
    `Basic Colors` 才是这一页画的画面。单词标题被跳过（要求含空格），
    所以这里返回 `Basic Colors` 而不是 `Colors` —— 这正是想要的。
    """
    assert mod.extract_topic_label("24\nColors\nBasic Colors\n1. red\n") == "Basic Colors"
    assert mod.extract_topic_label("61\nA Kitchen\n1. cabinet\n") == "A Kitchen"


def test_topic_label_none_when_page_has_no_heading():
    assert mod.extract_topic_label("1. red\n2. blue\n") is None


def test_ocr_page_number_noise_is_not_an_entry():
    """实测文本层里有 `poge1t`（页码 OCR 错读），不能当成词条。"""
    words = mod.extract_page_entries("poge1t\n1. cabinet\n")
    assert words == ["cabinet"]


def test_entry_regex_requires_a_leading_letter():
    """第一版把字符类写成 `[a-Za-z]`（小写 a）→ Python 解析成非法区间 `a-Z`。

    这个 typo 让整个脚本在 import 时就抛 re.PatternError，而它**不会**被
    「肉眼看正则」发现 —— 必须能跑起来。故留一条最小回归。
    """
    import re

    re.compile(mod._ENTRY_RE.pattern)  # 不抛即通过
    assert mod.extract_page_entries("1. cabinet\n") == ["cabinet"]


# ── 负面结论：OPD 解决不了义项对齐 ────────────────────────────────────────


def test_opd_does_not_cover_the_polysemous_words_that_need_it():
    """**钉住负面结论。**

    20 词人工审查发现的问题 #3（画面与语境句义项不一致）最严重的几个词
    —— `blind`/`wet`/`fine`/`deer`/`credit`/`type` —— **一个都不在 OPD 里**。
    它是入门级图解词典，覆盖的是 basic concrete nouns（bedroom/kitchen/bus stop）。

    后果：不能用 OPD 选义项。实测它确实有 `blind`，但形式是
    `mini-blinds`（主题 A Bedroom）—— 也就是说按 OPD 选义项会把 `blind`
    **钉死在「百叶窗」这个冷门义项上**，比现状更糟。
    """
    anchors_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "external"
        / "vocab_src"
        / "opd_topic_anchors.json"
    )
    if not anchors_path.exists():  # 源文件不入库，没抽过就跳过
        import pytest

        pytest.skip("opd_topic_anchors.json 未生成（需先跑 parse_opd_topic_anchors.py）")
    import json

    m = {r["word"]: r["topic"] for r in json.loads(anchors_path.read_text("utf-8"))}
    for w in ("blind", "wet", "fine", "deer", "credit", "type"):
        assert w not in m, f"{w} 竟在 OPD 里 —— 负面结论需重新评估"
    # 而它在的那几个是基础具体名词，义项问题本来就不严重
    assert m.get("bed") == "A Bedroom"

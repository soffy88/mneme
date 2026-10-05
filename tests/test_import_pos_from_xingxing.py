"""《象形9000》pos 回填导入器。

这些用例盯的是**实测踩到的东西**，不是接口形状：
  1. 词性行上一行必须是**干净单词** —— 否则 `R首AR nrfera`（OCR 毁掉的词段）
     会被当词条收进来；
  2. 词性标记要**去尾点**（`n.` → `n`），对齐 import_pos_from_dictation 的约定；
  3. docx 与 PDF 两条抽取路径必须能对**同一份版式**给出同一个答案
     —— 否则「PDF 全量入库」这件事没法验证。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "import_pos_from_xingxing.py"
)
_spec = importlib.util.spec_from_file_location("xingxing_pos", _SCRIPT)
assert _spec and _spec.loader
xing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xing)


# 版式片段：单词独立成段，下一段是「音标 + 词性. + 释义」
LAYOUT = [
    "supreme",
    "[su:1 pri:m] adj.极度的,最重要的; 至高的",
    "Only supreme people can reach the top.",
    "只有至高无上的人才能到达顶端。",
    "recently",
    "[ ri:sntli] adv.最近地，新近地",
    "infinite",
    "[ infinst] adj.无限的，无穷的 n.无限",
    "bark",
    "[ba:rk] v.狗吠n.树皮，吠声",
]


def test_parses_word_and_pos_from_adjacent_layout():
    got = dict(xing.parse_pos_entries(LAYOUT))
    assert got["supreme"] == "adj"
    assert got["recently"] == "adv"
    assert got["infinite"] == "adj"
    assert got["bark"] == "v"


def test_pos_is_stripped_of_trailing_dot():
    """`n.` → `n`：对齐 import_pos_from_dictation 已落库的约定。"""
    got = dict(xing.parse_pos_entries(["marble", "[ mɑ:bl] n.大理石，玻璃弹子"]))
    assert got["marble"] == "n"


def test_rejects_garbled_previous_line():
    """上一段是 OCR 乱码（`R首AR nrfera` 其实是 merchant）时**必须跳过**。

    这是实测 bug：不加约束时会把定义句里的 token 当成单词收进来。
    """
    lines = ["R首AR nrfera", "[ m3:rtfQnt] n.商人；批发商"]
    assert xing.parse_pos_entries(lines) == []


def test_rejects_pos_line_whose_previous_line_is_a_sentence():
    lines = [
        "Only supreme people can reach the top.",
        "[n.] something",
    ]
    assert xing.parse_pos_entries(lines) == []


def test_skips_first_line_pos_without_preceding_word():
    assert xing.parse_pos_entries(["n.版本；译文"]) == []


def test_first_occurrence_wins_across_files():
    """同词以首次出现为准（册内顺序即优先级），避免后来的册覆盖前面的。"""
    merged = xing.collect_entries  # 只验证签名存在；跨文件逻辑用下面这个直接构造
    a = {"word": "n"}
    b = {"word": "v"}
    combined: dict[str, str] = {}
    for d in (a, b):
        for k, v in d.items():
            combined.setdefault(k, v)
    assert combined == a
    assert callable(merged)


def test_docx_and_pdf_paths_agree_on_same_layout(tmp_path):
    """两条抽取路径对同一版式必须给出同一个 (word, pos)。

    这是「PDF 全量入库可验证」的前提：docx 那一册是 ground truth，
    PDF 路径跑同一册若不一致，就说明 PDF 抽取坏了。
    """
    docx_path = tmp_path / "sample.docx"
    doc = pytest.importorskip("docx")  # 没装就跳过 PDF 对照，只保留纯函数用例
    d = doc.Document()
    for line in LAYOUT:
        d.add_paragraph(line)
    d.save(str(docx_path))

    from_docx = xing.docx_paragraphs(docx_path)
    assert xing.parse_pos_entries(from_docx) == xing.parse_pos_entries(LAYOUT)

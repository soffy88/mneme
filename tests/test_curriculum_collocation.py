"""scripts/extract_curriculum_collocation.py 的解析回归测试。

钉住三个**已发生过的静默错误**：

1. 行对齐用 y 聚类 → 词与释义整体错位（`pressure→王子`）。现在由 PDF 矢量
   表格线建单元格保证；`profile_columns` / `cell_of` 必须守住这个前提。
2. 列下标硬编码 col==2 → 词义列实际在 c2/c3/c4 之间跳（p1=c2,p2=c4,p4=c3…），
   硬编码导致 81 行找不到词义。必须按内容特征判定列角色。
3. 一个单元格里有多条搭配时，只在第一个汉字处切 → 第二条搭配的英文混进
   第一条的 phrase_cn（`traffic accident` 的中文里塞进了 `by accident`）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "extract_curriculum_collocation.py"
    spec = importlib.util.spec_from_file_location("extract_curriculum_collocation", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ── 单元格网格 ─────────────────────────────────────────────────────────────


def test_cell_of_picks_correct_column():
    ys = [0, 10, 20, 30]
    xs = [0, 5, 10, 15]
    assert mod.cell_of(2, 7, ys, xs) == (0, 0)
    assert mod.cell_of(7, 7, ys, xs) == (0, 1)
    assert mod.cell_of(12, 17, ys, xs) == (1, 2)


def test_cell_of_clamps_outside_bounds():
    """OCR 框略微越出表格线时不该丢内容，而是夹到最近的格子里。"""
    ys = [10, 20, 30]
    xs = [10, 20, 30]
    assert mod.cell_of(-5, -5, ys, xs) == (0, 0)
    assert mod.cell_of(999, 999, ys, xs) == (1, 1)


def test_drop_slivers_removes_degenerate_column():
    """实测 386.5 与 390.0 只差 3.5pt，多出伪列会把文本挤到错误下标。"""
    assert mod._drop_slivers([43.8, 72.1, 137.3, 262.0, 324.6, 386.5, 390.0]) == [
        43.8, 72.1, 137.3, 262.0, 324.6, 386.5
    ]


# ── 列角色判定（替代硬编码下标）─────────────────────────────────────────────


def _mk(cols: dict) -> dict:
    """{col_index: [每行的文本]} -> profile_columns 期望的 buckets。"""
    buckets = {}
    for c, texts in cols.items():
        for r, t in enumerate(texts):
            buckets[(r, int(c))] = [(0.0, t)]
    return buckets


def test_roles_detected_when_meaning_column_shifts():
    """同一个表结构，词义列下标不同，角色判定都必须正确。"""
    for meaning_col in (2, 3, 4):
        b = {
            0: ["1", "2", "3"],
            1: ["accident", "account", "alarm"],
            meaning_col: ["n.事故", "n.账户", "n.闹钟"],
            meaning_col + 1: ["by accident 偶然地", "", ""],
        }
        roles = mod.profile_columns(_mk(b))
        assert roles["word"] == 1, roles
        assert roles["meaning"] == meaning_col, roles
        assert roles["collo"] == [meaning_col + 1], roles


def test_roles_detect_seq_column():
    b = {0: ["1", "2", "3"], 1: ["apple", "run", "go"], 2: ["n.苹果", "v.跑", "v.走"]}
    roles = mod.profile_columns(_mk(b))
    assert roles["seq"] == 0
    assert roles["word"] == 1
    assert roles["meaning"] == 2


def test_roles_return_none_when_no_english_column():
    assert mod.profile_columns(_mk({0: ["一", "二", "三"]}))["word"] is None


# ── 搭配拆分 ────────────────────────────────────────────────────────────────


def test_single_collocation():
    assert mod.split_collocation("boiled water开水") == [("boiled water", "开水")]


def test_two_collocations_in_one_cell_not_merged():
    """回归：曾在第一个汉字处切一刀，第二条搭配的英文混进第一条的中文里。"""
    got = mod.split_collocation("traffic accident 交通事故 by accident 偶然地；意外地")
    assert got == [("traffic accident", "交通事故"), ("by accident", "偶然地；意外地")]


def test_three_collocations():
    got = mod.split_collocation("take a breath 深呼吸 hold your breath 闭气 out of breath 喘不上气")
    assert [e for e, _ in got] == ["take a breath", "hold your breath", "out of breath"]


def test_collation_with_parenthetical_chinese():
    """`（呼吸的)空气;吸气` 中文侧混了半角括号，仍要切干净。"""
    got = mod.split_collocation("out of breath（呼吸的）空气;吸气")
    assert got and got[0][0] == "out of breath"


def test_chinese_only_returns_empty():
    assert mod.split_collocation("只有中文没有英文") == []
    assert mod.split_collocation("") == []


def test_english_only_returns_empty():
    assert mod.split_collocation("just english") == []


# ── 校验门 ──────────────────────────────────────────────────────────────────


def test_pos_not_in_whitelist_rejects_ocr_noise():
    """`U.`（v. 的误读）必须在白名单外被拒 —— 此前 u 在白名单里导致 attack
    的 pos 被记成 u。"""
    rec = {"row": 1, "seq": "1", "word": "attack",
           "meaning": "U.攻击;袭击", "collocations": [], "rejected": []}
    ok, why = mod.validate(rec)
    assert ok is None
    assert why == "pos_not_in_whitelist"


def test_ocr_junk_prefix_rejected_not_cleaned():
    """`n.＆.疼痛` 剥掉合法词性后仍以垃圾记号开头 —— 拒绝，不启发式清洗。"""
    rec = {"row": 1, "seq": "1", "word": "ache",
           "meaning": "n.＆.疼痛", "collocations": [], "rejected": []}
    ok, why = mod.validate(rec)
    assert ok is None
    assert why == "ocr_junk_in_meaning"


def test_valid_record_passes():
    rec = {"row": 1, "seq": "1", "word": "account", "meaning": "n.账户",
           "collocations": ["a bank account 银行账户"], "rejected": []}
    ok, why = mod.validate(rec)
    assert why == "" and ok is not None
    assert ok["pos"] == "n" and ok["meaning"] == "账户"
    assert ok["collocations"] == [{"en": "a bank account", "zh": "银行账户"}]


def test_no_chinese_meaning_rejected():
    rec = {"row": 1, "seq": "1", "word": "account", "meaning": "n.",
           "collocations": [], "rejected": []}
    ok, why = mod.validate(rec)
    assert ok is None and why == "no_chinese_meaning"
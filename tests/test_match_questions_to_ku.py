"""CMM-Math → 人教 KU 匹配脚本的纯函数单测（不碰 Ollama/网络/DB）。

CRG 审查发现 scripts/match_questions_to_ku.py 全模块零测试覆盖。可纯测的函数：
build_ku_text（描述截断 40 字）、adjacent_grades（年级±1 / 高中合并池 / 非法回退）、
merge_ku_lists（去重保持顺序）。ollama_match/deepseek_match/process_one 依赖网络或
DB，留待脚本自带的真实匹配流程验证。"""

from __future__ import annotations

from scripts.match_questions_to_ku import adjacent_grades, build_ku_text, merge_ku_lists

# ── build_ku_text ─────────────────────────────────────────────────────────────


def test_build_ku_text_lines():
    kus = [
        {"id": "k1", "name": "一元一次方程"},
        {"id": "k2", "name": "分数", "description": "同分母与异分母加减"},
    ]
    text = build_ku_text(kus)
    assert text == "- k1 | 一元一次方程\n- k2 | 分数 | 同分母与异分母加减"


def test_build_ku_text_truncates_description():
    kus = [{"id": "k1", "name": "x", "description": "很" * 100}]
    text = build_ku_text(kus)
    desc = text.split("| ", 2)[2]
    assert len(desc) == 40  # 防超长候选击穿 Ollama 2048 context


def test_build_ku_text_empty():
    assert build_ku_text([]) == ""


# ── adjacent_grades ───────────────────────────────────────────────────────────


def test_adjacent_grades_mid():
    assert adjacent_grades("g5") == ["g4", "g5", "g6"]


def test_adjacent_grades_boundary_low():
    assert adjacent_grades("g1") == ["g1", "g2"]


def test_adjacent_grades_boundary_high():
    assert adjacent_grades("g9") == ["g8", "g9"]


def test_adjacent_grades_high_school_merged_pool():
    assert adjacent_grades("g10") == ["g10", "g11", "g12"]
    assert adjacent_grades("g12") == ["g10", "g11", "g12"]


def test_adjacent_grades_invalid_returns_self():
    assert adjacent_grades("xx") == ["xx"]


# ── merge_ku_lists ────────────────────────────────────────────────────────────


def test_merge_ku_lists_dedup_keeps_order():
    cache = {
        "g4": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "g5": [{"id": "b", "name": "B2"}, {"id": "c", "name": "C"}],
    }
    out = merge_ku_lists(cache, ["g4", "g5"])
    assert [k["id"] for k in out] == ["a", "b", "c"]


def test_merge_ku_lists_skips_empty_ids():
    cache = {"g4": [{"id": "", "name": "no-id"}, {"id": "x", "name": "X"}]}
    out = merge_ku_lists(cache, ["g4"])
    assert [k["id"] for k in out] == ["x"]


def test_merge_ku_lists_missing_grade():
    assert merge_ku_lists({}, ["g9"]) == []

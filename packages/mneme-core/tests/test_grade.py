"""Tests for deterministic objective grading (answer_match) — 决策 D2.1/D3.5。"""

import pytest

from mneme_core.oprim.grade import (
    SHORT_MATCH_THRESHOLD,
    answer_match,
    grade_objective,
)


# --- choice：归一化精确 ---
def test_choice_correct():
    r = answer_match("A", expected="A", qtype="choice")
    assert r.is_correct and r.score == 1.0


def test_choice_case_insensitive():
    assert answer_match("a", expected="A", qtype="choice").is_correct


def test_choice_wrong():
    r = answer_match("B", expected="A", qtype="choice")
    assert not r.is_correct and r.score == 0.0


# --- fill：新增域，归一化精确（决策 D3.5） ---
def test_fill_exact_after_normalise():
    assert answer_match(" 3.14 ", expected="3.14", qtype="fill").is_correct


def test_fill_fullwidth_nfkc_folding():
    """全角数字/字母经 NFKC 折叠后与半角相等（决策 D3.5：去全半角）。"""
    assert answer_match("１２３", expected="123", qtype="fill").is_correct
    assert answer_match("ＡＢ", expected="ab", qtype="fill").is_correct


def test_fill_wrong():
    assert not answer_match("3.15", expected="3.14", qtype="fill").is_correct


# --- short：SequenceMatcher ≥ 0.85（决策 D2.1） ---
def test_short_high_similarity_passes():
    r = answer_match("等差数列的通项公式", expected="等差数列通项公式", qtype="short")
    assert r.is_correct  # 仅差一个"的"，比值 > 0.85


def test_short_low_similarity_fails():
    r = answer_match("等差数列", expected="等差数列的通项公式", qtype="short")
    assert not r.is_correct  # 差异过大 < 0.85


def test_short_identical_passes():
    assert answer_match("勾股定理", expected="勾股定理", qtype="short").is_correct


def test_short_threshold_is_085():
    assert SHORT_MATCH_THRESHOLD == 0.85


# --- 护栏：域外一律 ValueError（open / 数学 solve 不进本模块） ---
def test_open_rejected():
    with pytest.raises(ValueError):
        answer_match("any", expected="any", qtype="open")


def test_solve_rejected():
    """数学 solve 必须路由 sympy，不得进 answer_match（决策 D2.1）。"""
    with pytest.raises(ValueError):
        answer_match("x=2", expected="x=2", qtype="solve")


# --- 单源：旧名 grade_objective 仍可用（委托到 answer_match） ---
def test_grade_objective_delegates():
    assert grade_objective("A", "A", "choice").is_correct
    with pytest.raises(ValueError):
        grade_objective("any", "any", "open")

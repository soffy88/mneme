"""_choice_prompt —— 选择题选项从 profiler 拼回题干（AA.9 第一步，纯函数）。"""

from __future__ import annotations

from services.mcp_router import _choice_prompt

PROFILER = {"options": "A、 1\nB、 4\nC、 5\n\n"}


def test_choice_appends_options():
    out = _choice_prompt("下列正确的是（ ）", "choice", PROFILER)
    assert "A、 1" in out and "B、 4" in out and "C、 5" in out
    assert out.startswith("下列正确的是（ ）")


def test_solve_untouched():
    assert _choice_prompt("求 x 的值", "solve", PROFILER) == "求 x 的值"


def test_stem_already_has_options_untouched():
    stem = "下列正确的是（ ）\nA. 甲\nB. 乙"
    assert _choice_prompt(stem, "choice", PROFILER) == stem


def test_no_options_in_profiler():
    assert _choice_prompt("下列正确的是（ ）", "choice", {}) == "下列正确的是（ ）"
    assert _choice_prompt("下列正确的是（ ）", "choice", None) == "下列正确的是（ ）"

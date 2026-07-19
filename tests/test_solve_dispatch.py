"""SV-1/SV-3 验收：solve_dispatch 对 7 类问题各自求解正确，且不引入新绕过。

SV-1：7 个内核类型（function/conic/derivative/trig/sequence/geometry3d/
probability）各自通过 solve_dispatch 求解正确（复用既有内核测试的期望值，
不是重新验证内核数学正确性本身——那是 S0 之前就该有、内核自己的职责）。

SV-3：Solve 包装（solve_dispatch 本身）不得引入新的沙箱绕过路径——它只是
"选内核+构造 Input dataclass+调用"，不直接 eval 任何字符串，不绕开内核内部
已经接入的 S0 加固。这里做结构性断言，复用 S0-1
（tests/test_sandbox_zero_bypass.py）确立的检查手法：grep 源码，确认
solve_dispatch.py 里没有裸 sympify/eval/exec 调用。
"""

from __future__ import annotations

from pathlib import Path

from oskill.solve_dispatch import solve_dispatch

SOLVE_DISPATCH_PATH = (
    Path(__file__).resolve().parent.parent / "vendor" / "oskill" / "solve_dispatch.py"
)


def test_function_kernel_solves_correctly():
    result = solve_dispatch(
        "function", "zeros", {"expression": "x**2-4", "variable": "x"}
    )
    assert result.solvable
    assert "-2" in result.answer and "2" in result.answer


def test_conic_kernel_solves_correctly():
    result = solve_dispatch("conic", "", {"expression": "x^2+y^2=25"})
    assert result.solvable
    assert "circle" in result.answer


def test_derivative_kernel_solves_correctly():
    result = solve_dispatch(
        "derivative",
        "derivative",
        {"expression": "x**3-3*x", "variable": "x"},
    )
    assert result.solvable
    assert result.answer == "3*x**2 - 3"


def test_trig_kernel_solves_correctly():
    result = solve_dispatch(
        "trig",
        "evaluate",
        {"expression": "sin(x)", "variable": "x", "angle_degrees": 30},
    )
    assert result.solvable
    assert "1/2" in result.answer


def test_sequence_kernel_solves_correctly():
    result = solve_dispatch("sequence", "nth_term", {"terms": [2, 4, 6, 8], "n": 10})
    assert result.solvable
    assert "20" in result.answer


def test_geometry3d_kernel_solves_correctly():
    result = solve_dispatch(
        "geometry3d", "distance", {"p1": [0, 0, 0], "p2": [3, 4, 0]}
    )
    assert result.solvable
    assert "distance = 5" in result.answer


def test_probability_kernel_solves_correctly():
    result = solve_dispatch("probability", "combinations", {"n": 5, "k": 2})
    assert result.solvable
    assert "10" in result.answer


def test_unknown_kernel_rejected_gracefully():
    result = solve_dispatch("bogus_kernel", "", {})
    assert result.solvable is False
    assert "Unknown kernel" in result.error


def test_unknown_task_rejected_gracefully():
    result = solve_dispatch("function", "bogus_task", {})
    assert result.solvable is False
    assert "Unknown task" in result.error


def test_missing_required_params_degrades_gracefully_not_crash():
    """sequence 缺 terms——必须优雅降级，不能抛未捕获异常。"""
    result = solve_dispatch("sequence", "nth_term", {"n": 5})
    assert result.solvable is False
    assert result.error != ""


def test_malformed_param_types_degrade_gracefully_not_crash():
    """LLM 产出的 params 弱类型——非数字字符串塞进数值字段必须优雅降级。"""
    result = solve_dispatch("geometry3d", "sphere", {"radius": "not_a_number"})
    assert result.solvable is False


def test_solve_dispatch_introduces_no_new_bypass_path():
    """SV-3 结构性断言：solve_dispatch.py 本身不得包含裸 eval/exec/sympify——
    它只应该做"选内核+构造 dataclass+调用"，任何字符串求值都必须发生在内核
    内部（已经过 S0 加固），不能在这一层再引入一条平行的、未加固的求值路径。
    """
    source = SOLVE_DISPATCH_PATH.read_text(encoding="utf-8")
    forbidden = ["sp.sympify(", "sympy.sympify(", "eval(", "exec("]
    offenders = [f for f in forbidden if f in source]
    assert not offenders, f"solve_dispatch.py 出现了裸求值调用：{offenders}"

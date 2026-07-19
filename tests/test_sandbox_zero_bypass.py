"""
S0-1 验收：7 个 solve_* oprim 内核全部经 obase.sympy_runtime 沙箱，0 绕过。

W4 前置查证最初只报告了 2 个绕过（solve_geometry3d/solve_probability，纯数值
dataclass in/out，没有表达式字符串）。写这条结构性测试时，进一步发现盘点
本身不完整：solve_conic/solve_derivative/solve_trig 三个内核虽然 import 了
SymPyRuntime，但从未实际调用——直接对调用方传入的表达式字符串跑裸
`sp.sympify()`，零 AST 白名单校验、零 fork/timeout/内存上限，这是比"数值
DoS"更严重的真代码注入风险面（同一类问题 sympify 历史上就是已知的沙箱逃逸
入口）。solve_sequence 同样 import 了却完全没用（连 sympy 都没 import，是纯
Python 数值运算，风险等级接近 geometry3d/probability）。

结论：7 个内核里，加固前只有 solve_function 一个真正接了沙箱——2 个纯数值、
4 个有真实代码注入风险面的字符串求值内核全部绕过（含 3 个"import 了但没用"
的半成品迁移状态）。这条测试是结构性断言：不针对某个内核的具体行为，而是
防未来再有新 solve_* 内核（或者半成品迁移）被悄悄漏网——import 一个符号不
代表真的调用了它，测试必须验证"真的调用"而不是"提到过"。
"""

from __future__ import annotations

from pathlib import Path

from obase.sandbox_selfcheck import (
    AST_VALIDATED_ENTRY_POINTS,
    EXPECTED_KERNELS,
    NUMERIC_ONLY_KERNELS,
    STRING_EVAL_KERNELS,
)

VENDOR_OPRIM = Path(__file__).resolve().parent.parent / "vendor" / "oprim"

# 常量单源于 obase.sandbox_selfcheck（该模块同时供容器启动时的生产自检
# check_or_die() 使用，见 tests/test_sandbox_selfcheck.py）——这里不再各自
# 维护一份副本，防止两处定义漂移。


def test_exactly_seven_solve_kernels_exist():
    """先固定基线：不多不少 7 个 solve_* 内核。多了/少了都说明这条测试的
    覆盖面假设过期了，需要更新 EXPECTED_KERNELS，而不是让下面的沙箱检查
    悄悄漏掉一个新内核。"""
    found = {p.name for p in VENDOR_OPRIM.glob("solve_*.py")}
    assert found == EXPECTED_KERNELS, (
        f"solve_* 内核清单变了（found={found}），"
        f"请更新本测试的 EXPECTED_KERNELS 并确认新增内核已接沙箱"
    )


def test_numeric_only_kernels_use_run_isolated():
    """纯数值内核必须走 run_isolated()——不能只是 import 了 SymPyRuntime 却
    从没调用（solve_sequence 加固前就是这样：import 了，连 sympy 本身都没
    用上，是完全绕过的死 import）。"""
    missing: list[str] = []
    for name in sorted(NUMERIC_ONLY_KERNELS):
        source = (VENDOR_OPRIM / name).read_text(encoding="utf-8")
        if "run_isolated" not in source:
            missing.append(name)
    assert not missing, f"以下纯数值内核没有调用 run_isolated()：{missing}"


def test_string_eval_kernels_actually_call_ast_validated_entry_points():
    """有表达式字符串的内核必须真的调用 SymPyRuntime 的 AST 校验入口——不能
    只是 import 了类名却从没调用任何方法（这正是加固前 solve_conic/
    solve_derivative/solve_trig 的真实状态：import 了 SymPyRuntime，但直接
    对调用方字符串跑裸 sp.sympify()，零校验）。"""
    missing: list[str] = []
    for name in sorted(STRING_EVAL_KERNELS):
        source = (VENDOR_OPRIM / name).read_text(encoding="utf-8")
        if not any(entry in source for entry in AST_VALIDATED_ENTRY_POINTS):
            missing.append(name)
    assert not missing, (
        f"以下内核有表达式字符串但没有调用任何 AST 校验入口，"
        f"可能在用 sp.sympify()/其他方式绕过白名单直接 eval：{missing}"
    )


def test_no_kernel_calls_raw_sympify_on_caller_string():
    """更进一步的负向断言：字符串求值内核不应再出现 ``sp.sympify(`` /
    ``sympy.sympify(`` 这种绕过 AST 校验的裸调用残留（加固前 solve_conic 有
    2 处、solve_derivative 有 1 处、solve_trig 有 2 处，都是直接对调用方
    表达式字符串跑裸 sympify，零沙箱）。数值内核不受此限——它们本来就没有
    表达式字符串，`sp` 都不一定被引用。"""
    offenders: dict[str, int] = {}
    for name in sorted(STRING_EVAL_KERNELS):
        source = (VENDOR_OPRIM / name).read_text(encoding="utf-8")
        count = source.count("sp.sympify(") + source.count("sympy.sympify(")
        if count:
            offenders[name] = count
    assert not offenders, f"以下内核仍有裸 sympify() 调用，绕过 AST 校验：{offenders}"

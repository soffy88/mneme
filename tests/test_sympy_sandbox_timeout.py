"""
X.3 红线测试：沙箱红线——病态 sympy 输入必须超时被杀，不能挂起进程。

实现在 vendor/obase/sympy_runtime.py（SymPyRuntime._run_with_timeout，fork子
进程+OS级SIGTERM/SIGKILL），全部四个 solve_* oprim（solve_function/solve_conic/
solve_derivative/solve_trig）都经它执行，不是绕开求解主链路单测一个孤立工具。

之前全仓库 grep sympy_runtime/RuntimeConfig/pathological/timeout 零匹配，这条
红线此前没有任何测试兜底。
"""

from __future__ import annotations

import time

import pytest

from obase.sympy_runtime import RuntimeConfig, SymPyRuntime, SymPyTimeoutError


def test_run_with_timeout_kills_hanging_computation():
    """直接测 _run_with_timeout 本身——这是四个 solve_* oprim 共用的唯一超时
    执行机制。用一个确定性挂起的函数（sleep）代替"碰运气式"的病态sympy表达式，
    避免不同机器上真实sympy运算耗时不稳定导致测试flaky；测的是杀进程的机制，
    不是某个具体表达式碰巧慢不慢。"""
    rt = SymPyRuntime(RuntimeConfig(timeout_seconds=0.3))
    start = time.monotonic()
    with pytest.raises(SymPyTimeoutError):
        rt._run_with_timeout(lambda: time.sleep(5))
    elapsed = time.monotonic() - start
    # 必须在超时附近被杀，不能真的等满5秒（证明子进程真被kill，不是等它跑完）
    assert elapsed < 2.0
    print(f"  挂起5秒的计算在 {elapsed:.2f}s 内被杀（超时设为0.3s）✓")


def test_pathological_high_degree_polynomial_gets_killed_via_real_solver():
    """端到端：通过 solve_function（真实求解主链路，非孤立测沙箱工具）喂一个
    80次高次多项式求零点——sympy 通用求解器对这种输入基本必然抛不出解析解，
    会一直churn。断言：(1) 调用在有界时间内返回，不是挂起；(2) solvable=False
    优雅降级，不是抛未捕获异常/500；(3) error 信息里能看到是被沙箱两道墙之一
    （超时或内存上限，S0 加固后 max_memory_bytes 真正 enforce 了）杀的，不是
    别的原因失败——两道墙哪道先触发取决于具体病态输入的资源消耗模式，都是
    同一条红线（病态输入必须被杀）的体现，不是只认超时。"""
    from oprim.solve_function import FunctionSolveInput, solve_function

    start = time.monotonic()
    result = solve_function(
        FunctionSolveInput(
            expression="x**80 + x**79 + x**3 + 1",
            variable="x",
            task="zeros",
            timeout=0.5,
        )
    )
    elapsed = time.monotonic() - start
    assert elapsed < 5.0  # 有界时间内返回，没有挂起等它跑完
    assert result.solvable is False
    error_lower = (result.error or "").lower()
    assert "timeout" in error_lower or "memory limit" in error_lower
    print(
        f"  80次多项式求零点在 {elapsed:.2f}s 内被沙箱杀掉并优雅降级"
        f"（solvable=False, error={result.error!r}），不是挂起或500 ✓"
    )

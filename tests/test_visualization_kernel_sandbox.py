"""kernel_to_plot2d.py / kernel_to_three.py 沙箱加固验收（W4 Visualize 前置）。

在给 Visualize 模式接线的过程中发现：这两个既有可视化内核（W2 时代已存在，
被 vendor/oskill/solve_and_visualize.py 使用）跟 S0 加固前的 solve_conic/
derivative/trig/function 是同一类真实漏洞——直接对调用方（Visualize 模式下
是 LLM）提供的表达式字符串跑裸 sympy 解析，零 AST 白名单、零 fork/timeout/
内存上限。S0 的范围只覆盖了 7 个 solve_* 内核，没有覆盖这两个——因为它们不
在"solve_*"命名下，之前的沙箱盘点没扫到。这条测试补上这个缺口，同时防止
未来任何新的可视化内核再犯同样的错（obase/sandbox_selfcheck.py 的
VISUALIZATION_KERNELS 现在覆盖这两个文件，生产启动自检也会拦）。
"""

from __future__ import annotations

import time
from pathlib import Path

from oprim.kernel_to_plot2d import Plot2DRequest, kernel_to_plot2d
from oprim.kernel_to_three import Plot3DRequest, kernel_to_three

VENDOR_OPRIM = Path(__file__).resolve().parent.parent / "vendor" / "oprim"

MALICIOUS_EXPRESSION = "__import__('os').system('id')"


def test_plot2d_legitimate_expression_still_works():
    result = kernel_to_plot2d(
        Plot2DRequest(expression="x**2 - 4", variable="x", num_points=50)
    )
    assert len(result.x_values) == 50
    assert len(result.y_values) == 50


def test_plot2d_malicious_expression_does_not_execute_and_degrades_gracefully():
    start = time.monotonic()
    result = kernel_to_plot2d(
        Plot2DRequest(expression=MALICIOUS_EXPRESSION, variable="x")
    )
    elapsed = time.monotonic() - start
    assert result.x_values == []
    assert result.y_values == []
    assert elapsed < 5.0


def test_plot2d_num_points_is_capped_against_dos():
    from oprim.kernel_to_plot2d import _MAX_NUM_POINTS

    result = kernel_to_plot2d(
        Plot2DRequest(expression="x", variable="x", num_points=1_000_000)
    )
    assert len(result.x_values) <= _MAX_NUM_POINTS


def test_three_legitimate_expression_still_works():
    result = kernel_to_three(
        Plot3DRequest(expression="x**2 + y**2", x_var="x", y_var="y", grid_points=10)
    )
    assert len(result.x_values) == 100  # 10*10 grid
    assert len(result.z_values) == 100


def test_three_malicious_expression_does_not_execute_and_degrades_gracefully():
    start = time.monotonic()
    result = kernel_to_three(
        Plot3DRequest(expression=MALICIOUS_EXPRESSION, x_var="x", y_var="y")
    )
    elapsed = time.monotonic() - start
    assert result.x_values == []
    assert result.z_values == []
    assert elapsed < 5.0


def test_three_grid_points_is_capped_against_dos():
    from oprim.kernel_to_three import _MAX_GRID_POINTS

    result = kernel_to_three(
        Plot3DRequest(expression="x + y", x_var="x", y_var="y", grid_points=10_000)
    )
    assert len(result.x_values) <= _MAX_GRID_POINTS**2


def test_no_bypass_structural_check():
    """同 S0-1 的结构性零绕过断言，覆盖这两个可视化内核——单源常量见
    obase.sandbox_selfcheck.VISUALIZATION_KERNELS。"""
    from obase.sandbox_selfcheck import (
        AST_VALIDATED_ENTRY_POINTS,
        VISUALIZATION_KERNELS,
    )

    for name in sorted(VISUALIZATION_KERNELS):
        source = (VENDOR_OPRIM / name).read_text(encoding="utf-8")
        assert any(e in source for e in AST_VALIDATED_ENTRY_POINTS), (
            f"{name} 没有调用任何 AST 校验入口"
        )
        assert "sp.sympify(" not in source and "sympy.sympify(" not in source, (
            f"{name} 残留裸 sympify() 调用"
        )

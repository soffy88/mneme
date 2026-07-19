"""visualize_dispatch —— Visualize 模式渲染数据调度层（W4 §3，去 Manim）。

给定结构化 VisualizeTaskPlan 数据（render_type/params），产出对应的渲染
数据：

- ``svg_plot``/``three``/``chart``：调用既有确定性内核
  （kernel_to_plot2d/kernel_to_three/solve_sequence，均已 S0 加固，本轮
  Visualize 前置修复了 kernel_to_plot2d/kernel_to_three 里遗留的裸 sympify
  绕过——见 tests/test_visualization_kernel_sandbox.py）——渲染数据 100%
  来自内核真实输出，不经 LLM 二次处理（VZ-4）。
- ``mermaid``：**不是**内核数据，是 LLM 直接撰写的声明式图示文本（同
  Solve 模式 narration 的处置原则一致：诚实标注来源，不伪装成内核派生
  数据）——``data_source`` 字段对每种类型如实标注，前端/审计都能看出
  这条区分。

VZ-3（无服务端代码执行）：本层任何分支都不 eval/exec 任何字符串——kernel_to_
plot2d/kernel_to_three 内部虽然要解析数学表达式，但走的是 S0 加固后的
SymPyRuntime（AST 白名单 + fork 沙箱），不是裸执行；mermaid 分支只做字符串
透传 + 关键词黑名单防御性检查（真正的解析发生在客户端 mermaid.js 库里，
库本身不 eval 任意 JS，只解析自己的声明式图表 DSL）。返回值全是 JSON 可
序列化的原始数据（数字/字符串/列表/字典），不含任何"可执行代码"字段。

FC-6：无 Mneme 专属假设（"选渲染类型+调用"是通用调度逻辑），留在
vendor/oskill（3O 共享层）；读取 mneme-core 的 VISUALIZE_RENDER_TYPES 作为
单一权威来源。
"""

from __future__ import annotations

from typing import Any

from mneme_core.oprim.models import VISUALIZE_RENDER_TYPES

_MAX_SEQUENCE_TERMS = 60


def _as_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_range_or_default(v: Any, default: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return default
    lo, hi = _as_float_or_none(v[0]), _as_float_or_none(v[1])
    if lo is None or hi is None or lo >= hi:
        return default
    return (lo, hi)


def _as_float_list_or_none(v: Any) -> list[float] | None:
    if not isinstance(v, (list, tuple)):
        return None
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return None


def _fail(render_type: str, error: str) -> dict[str, Any]:
    return {"success": False, "render_type": render_type, "error": error}


def _dispatch_svg_plot(params: dict[str, Any]) -> dict[str, Any]:
    from oprim.generate_svg_diagram import generate_svg_diagram
    from oprim.kernel_to_plot2d import Plot2DRequest, kernel_to_plot2d

    expression = str(params.get("expression", ""))
    variable = str(params.get("variable", "x"))
    x_range = _as_range_or_default(params.get("x_range"), (-10.0, 10.0))

    plot_data = kernel_to_plot2d(
        Plot2DRequest(expression=expression, variable=variable, x_range=x_range)
    )
    if not plot_data.x_values:
        return _fail("svg_plot", "表达式无法求值（可能非法或不在定义域内）")

    svg = generate_svg_diagram(plot_data)
    return {
        "success": True,
        "render_type": "svg_plot",
        "svg": svg,
        "title": plot_data.title,
        "data_source": "kernel_to_plot2d",
    }


def _dispatch_three(params: dict[str, Any]) -> dict[str, Any]:
    from oprim.kernel_to_three import Plot3DRequest, kernel_to_three

    expression = str(params.get("expression", ""))
    x_var = str(params.get("x_var", "x"))
    y_var = str(params.get("y_var", "y"))
    x_range = _as_range_or_default(params.get("x_range"), (-5.0, 5.0))
    y_range = _as_range_or_default(params.get("y_range"), (-5.0, 5.0))

    data = kernel_to_three(
        Plot3DRequest(
            expression=expression,
            x_var=x_var,
            y_var=y_var,
            x_range=x_range,
            y_range=y_range,
        )
    )
    if not data.x_values:
        return _fail("three", "表达式无法求值（可能非法或不在定义域内）")

    return {
        "success": True,
        "render_type": "three",
        "points": {"x": data.x_values, "y": data.y_values, "z": data.z_values},
        "title": data.title,
        "data_source": "kernel_to_three",
    }


def _dispatch_chart(params: dict[str, Any]) -> dict[str, Any]:
    mode = str(params.get("mode", "function"))

    if mode == "function":
        from oprim.kernel_to_plot2d import Plot2DRequest, kernel_to_plot2d

        expression = str(params.get("expression", ""))
        variable = str(params.get("variable", "x"))
        plot_data = kernel_to_plot2d(
            Plot2DRequest(expression=expression, variable=variable, num_points=60)
        )
        if not plot_data.x_values:
            return _fail("chart", "表达式无法求值（可能非法或不在定义域内）")
        return {
            "success": True,
            "render_type": "chart",
            "chart_type": "line",
            "labels": [f"{x:.2f}" for x in plot_data.x_values],
            "datasets": [{"label": expression, "data": plot_data.y_values}],
            "data_source": "kernel_to_plot2d",
        }

    if mode == "sequence":
        from oprim.solve_sequence import SequenceSolveInput, solve_sequence

        terms = _as_float_list_or_none(params.get("terms"))
        if terms is None or len(terms) < 2:
            return _fail("chart", "sequence 模式需要至少 2 项 terms")
        terms = terms[:_MAX_SEQUENCE_TERMS]

        check = solve_sequence(SequenceSolveInput(terms=terms, task="type_check"))
        if not check.solvable:
            return _fail("chart", check.error or "无法识别数列类型")

        return {
            "success": True,
            "render_type": "chart",
            "chart_type": "bar",
            "labels": [str(i + 1) for i in range(len(terms))],
            "datasets": [{"label": check.answer, "data": terms}],
            "data_source": "solve_sequence",
        }

    return _fail("chart", f"未知 chart mode: {mode!r}")


def _dispatch_mermaid(params: dict[str, Any]) -> dict[str, Any]:
    diagram_source = str(params.get("diagram_source", "")).strip()
    if not diagram_source:
        return _fail("mermaid", "mermaid 缺少 diagram_source")
    return {
        "success": True,
        "render_type": "mermaid",
        "diagram_source": diagram_source,
        # 诚实标注：这不是内核派生数据，是 LLM 直接撰写的声明式图示文本
        # （同 Solve 模式 narration 的处置原则一致）。
        "data_source": "llm_authored",
    }


def visualize_dispatch(render_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """render_type/params -> 渲染数据字典。

    render_type 不合法/必需参数缺失/类型不对 -> success=False + error，
    绝不抛未捕获异常给调用方。"""
    if render_type not in VISUALIZE_RENDER_TYPES:
        return _fail(render_type, f"Unknown render_type: {render_type!r}")

    try:
        if render_type == "svg_plot":
            return _dispatch_svg_plot(params)
        elif render_type == "three":
            return _dispatch_three(params)
        elif render_type == "chart":
            return _dispatch_chart(params)
        elif render_type == "mermaid":
            return _dispatch_mermaid(params)
        else:
            return _fail(render_type, f"Unhandled render_type: {render_type!r}")
    except (TypeError, ValueError) as exc:
        return _fail(render_type, f"Invalid params: {exc}")


__all__ = ["visualize_dispatch"]

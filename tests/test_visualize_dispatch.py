"""VZ-1/VZ-3/VZ-4 验收：visualize_dispatch 对 4 类渲染类型各自产出正确、
真实、来源可溯的数据，且无服务端代码执行。

VZ-1：4 种渲染类型（svg_plot/three/chart-function/chart-sequence/mermaid）
各自产出正确的渲染数据。

VZ-3：本层不得引入服务端代码执行——结构性断言 visualize_dispatch.py 本身
没有裸 eval/exec/sympify（真正的表达式求值发生在已加固的
kernel_to_plot2d/kernel_to_three 内部）。

VZ-4：svg_plot/three/chart 三种类型的 data_source 必须指向真实内核
（kernel_to_plot2d/kernel_to_three/solve_sequence）；mermaid 类型诚实标注
为 llm_authored，不伪装成内核数据。
"""

from __future__ import annotations

from pathlib import Path

from oskill.visualize_dispatch import visualize_dispatch

VENDOR_OSKILL = (
    Path(__file__).resolve().parent.parent
    / "vendor"
    / "oskill"
    / "visualize_dispatch.py"
)

MALICIOUS_EXPRESSION = "__import__('os').system('id')"


def test_svg_plot_produces_real_svg_from_kernel():
    result = visualize_dispatch("svg_plot", {"expression": "x**2 - 4", "variable": "x"})
    assert result["success"] is True
    assert "<svg" in result["svg"]
    assert result["data_source"] == "kernel_to_plot2d"


def test_three_produces_real_points_from_kernel():
    result = visualize_dispatch(
        "three", {"expression": "x**2 + y**2", "x_var": "x", "y_var": "y"}
    )
    assert result["success"] is True
    assert len(result["points"]["x"]) > 0
    assert len(result["points"]["x"]) == len(result["points"]["z"])
    assert result["data_source"] == "kernel_to_three"


def test_chart_function_mode_produces_real_samples_from_kernel():
    result = visualize_dispatch(
        "chart", {"mode": "function", "expression": "sin(x)", "variable": "x"}
    )
    assert result["success"] is True
    assert result["chart_type"] == "line"
    assert len(result["labels"]) > 0
    assert result["data_source"] == "kernel_to_plot2d"


def test_chart_sequence_mode_produces_real_terms_from_kernel():
    result = visualize_dispatch("chart", {"mode": "sequence", "terms": [2, 4, 6, 8]})
    assert result["success"] is True
    assert result["chart_type"] == "bar"
    assert result["datasets"][0]["data"] == [2.0, 4.0, 6.0, 8.0]
    assert result["data_source"] == "solve_sequence"


def test_mermaid_is_honestly_labeled_as_llm_authored_not_kernel_data():
    """VZ-4 的诚实性核心断言：mermaid 内容不是内核数据，data_source 必须
    如实标注为 llm_authored，不能冒充成任何内核名字。"""
    result = visualize_dispatch(
        "mermaid", {"diagram_source": "flowchart TD\nA[开始]-->B[结束]"}
    )
    assert result["success"] is True
    assert result["data_source"] == "llm_authored"
    assert result["diagram_source"] == "flowchart TD\nA[开始]-->B[结束]"


def test_unknown_render_type_rejected_gracefully():
    result = visualize_dispatch("matplotlib_3d", {})
    assert result["success"] is False
    assert "Unknown render_type" in result["error"]


def test_malicious_expression_in_svg_plot_does_not_execute():
    result = visualize_dispatch("svg_plot", {"expression": MALICIOUS_EXPRESSION})
    assert result["success"] is False


def test_malicious_expression_in_three_does_not_execute():
    result = visualize_dispatch("three", {"expression": MALICIOUS_EXPRESSION})
    assert result["success"] is False


def test_malicious_expression_in_chart_function_does_not_execute():
    result = visualize_dispatch(
        "chart", {"mode": "function", "expression": MALICIOUS_EXPRESSION}
    )
    assert result["success"] is False


def test_missing_required_params_degrade_gracefully_not_crash():
    result = visualize_dispatch("chart", {"mode": "sequence"})  # 缺 terms
    assert result["success"] is False
    assert result["error"] != ""


def test_visualize_dispatch_introduces_no_server_side_code_execution():
    """VZ-3 结构性断言：本层不得包含裸 eval/exec/sympify——任何数学表达式
    求值都必须发生在已加固的内核内部，这一层只做"选类型+构造参数+调用"。"""
    source = VENDOR_OSKILL.read_text(encoding="utf-8")
    forbidden = ["sp.sympify(", "sympy.sympify(", "eval(", "exec("]
    offenders = [f for f in forbidden if f in source]
    assert not offenders, f"visualize_dispatch.py 出现了裸求值/执行调用：{offenders}"

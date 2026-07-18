"""C5 红线：memory 是呈现层上下文，不进门控判据。

静态断言 services/memory.py 不 import 任何门控/判分模块——防未来有人顺手让
merge/recall 的结果影响 is_mastered/process_interaction。对照 C3 persona 同一
红线测试（tests/test_persona_no_gating_coupling.py）。
"""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_IMPORTS = (
    "mastery_gate",
    "gate_store",
    "math_grade",
    "verdict_guard",
    "cognitive_service",
    "process_interaction",
    "answer_match",
)

_MEMORY_MODULE = Path(__file__).parent.parent / "services" / "memory.py"


def _imported_module_names(source: str) -> set[str]:
    """AST 解析实际 import 的模块名（不误命中文档字符串/注释里同名的说明文字）。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def test_memory_module_never_imports_gating_or_grading_modules():
    source = _MEMORY_MODULE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)]
    assert not hits, (
        f"memory.py 实际 import 了门控/判分相关模块 {hits}——违反红线"
        "（memory 是呈现层上下文，不进门控判据）"
    )


def test_gating_functions_have_no_memory_parameter():
    """C5 验收：门控/判分函数签名里没有、也不可能有 memory 相关参数——结构性不耦合。"""
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective
    from services.cognitive_service import process_interaction

    for fn in (is_mastered, next_objective, process_interaction):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any("memory" in p for p in params), (
            f"{fn.__qualname__} 出现 memory 相关参数——违反红线"
        )


def test_recall_is_read_only_no_write_capable_signature():
    """recall 只读召回：不接受 content/topic-写入类参数（防被误用成写入口）。"""
    import inspect

    from services.memory import recall

    params = set(inspect.signature(recall).parameters)
    assert "content" not in params

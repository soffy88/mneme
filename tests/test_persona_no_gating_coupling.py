"""C3 红线：persona 只改"怎么讲"，不改"学什么/过没过门"。

静态断言 services/persona_store.py 不 import 任何门控/判分模块——防未来有人
顺手往 persona 里塞判分逻辑。真 DB 读路径另测行为（test_persona_store.py）。
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

_PERSONA_STORE = Path(__file__).parent.parent / "services" / "persona_store.py"


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


def test_persona_store_never_imports_gating_or_grading_modules():
    source = _PERSONA_STORE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)]
    assert not hits, (
        f"persona_store.py 实际 import 了门控/判分相关模块 {hits}——违反红线"
        "（persona 只改怎么讲，不改学什么/过没过门）"
    )


def test_render_for_prompt_is_pure_string_function():
    """render_for_prompt 是无 IO 纯函数：不接受 db/session 参数。"""
    import inspect

    from services.persona_store import render_for_prompt

    sig = inspect.signature(render_for_prompt)
    assert list(sig.parameters) == ["persona"]
    assert not inspect.iscoroutinefunction(render_for_prompt)


def test_gating_functions_have_no_persona_parameter():
    """C3-2 验收：门控/判分函数签名里没有、也不可能有 persona 参数——结构性不耦合。"""
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective
    from services.cognitive_service import process_interaction

    for fn in (is_mastered, next_objective, process_interaction):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any("persona" in p for p in params), (
            f"{fn.__qualname__} 出现 persona 相关参数——违反红线"
        )

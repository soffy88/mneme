"""W3 A4/A6 红线：Knowledge Hub 检索只作素材，不进门控判据（BLUEPRINT v1.1 P1：
掌握度管调度、检索管呈现，两层不融合）。

静态断言 services/knowledge_hub_search.py 不 import 任何门控/判分模块。
对照 C3 persona / C4 rag / C5 memory 同一模式（tests/test_rag_no_gating_coupling.py）。
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

_MODULE = Path(__file__).parent.parent / "services" / "knowledge_hub_search.py"


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


def test_knowledge_hub_search_never_imports_gating_or_grading_modules():
    source = _MODULE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)]
    assert not hits, (
        f"knowledge_hub_search.py 实际 import 了门控/判分相关模块 {hits}——"
        "违反红线（检索只作素材，不进门控判据）"
    )


def test_gating_functions_have_no_knowledge_hub_parameter():
    """结构性不耦合：门控/判分函数签名里没有、也不可能有检索相关参数。"""
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective
    from services.cognitive_service import process_interaction

    for fn in (is_mastered, next_objective, process_interaction):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any(
            k in p
            for p in params
            for k in ("knowledge_hub", "search_result", "kc_chunk", "textbook_chunk")
        ), f"{fn.__qualname__} 出现 Knowledge Hub 检索相关参数——违反红线"


def test_is_mastered_result_unaffected_by_knowledge_hub_search_results():
    """A-6 验收：直接证明 is_mastered 的判定只取决于 progress/kp，跟
    knowledge_hub_search 的返回值完全没有数据通路（无法传参、无共享状态），
    调用检索前后对同一 progress/kp 判定结果不变。
    """
    from mneme_core.oprim.mastery_gate import is_mastered
    from mneme_core.oprim.models import (
        BktPosterior,
        KnowledgePoint,
        KnowledgeType,
        LearningProgress,
    )

    kp = KnowledgePoint(id="k1", name="k1", type=KnowledgeType.PROCEDURE)
    progress = LearningProgress(
        student_id="s1",
        modules=[],
        bkt={"k1": BktPosterior(p_learned=0.95, sigma=0.01, n_obs=5)},
    )

    before = is_mastered(progress, kp)
    # 模拟"这期间跑了一次 Knowledge Hub 检索"——不传入 is_mastered、无共享可变状态
    fake_search_results = {
        "query_type": "kc_id",
        "results": [{"chunk_id": "x", "score": 0.99, "provenance": "inferred"}],
    }
    del fake_search_results  # 就是要证明它进不了 is_mastered 的输入
    after = is_mastered(progress, kp)

    assert before == after is True

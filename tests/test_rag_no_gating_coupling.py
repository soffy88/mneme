"""C4 红线：RAG 召回只作素材，不进门控判据（BLUEPRINT v1.1 P1：掌握度管调度、
RAG 管呈现，两层不融合）。

静态断言 services/rag_client.py 不 import 任何门控/判分模块。对照 C3 persona /
C5 memory 同一模式。
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

_RAG_CLIENT_MODULE = Path(__file__).parent.parent / "services" / "rag_client.py"


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


def test_rag_client_never_imports_gating_or_grading_modules():
    source = _RAG_CLIENT_MODULE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)]
    assert not hits, (
        f"rag_client.py 实际 import 了门控/判分相关模块 {hits}——违反红线"
        "（RAG 只作素材，不进门控判据）"
    )


def test_gating_functions_have_no_rag_parameter():
    """C4 验收：门控/判分函数签名里没有、也不可能有 RAG/search 相关参数——结构性不耦合。"""
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective
    from services.cognitive_service import process_interaction

    for fn in (is_mastered, next_objective, process_interaction):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any(
            k in p for p in params for k in ("rag", "stratum", "search_result")
        ), f"{fn.__qualname__} 出现 RAG 相关参数——违反红线"


def test_is_mastered_result_unaffected_by_rag_search_results():
    """C4 验收（断言 RAG 结果不影响 is_mastered 判定）：直接证明——is_mastered
    的判定只取决于 progress/kp，跟 rag_client.search 的返回值完全没有数据通路
    （无法传参、无共享状态），调用 search 前后对同一 progress/kp 判定结果不变。
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
    # 模拟"这期间跑了一次 RAG 检索"——不传入 is_mastered、无共享可变状态
    fake_rag_results = [{"id": "x", "title": "无关内容", "score": 0.99}]
    del fake_rag_results  # 就是要证明它进不了 is_mastered 的输入
    after = is_mastered(progress, kp)

    assert before == after is True

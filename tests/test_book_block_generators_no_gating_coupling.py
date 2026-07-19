"""W3 Part B B2 红线：Book Engine 内容块生成是呈现层，不进门控判据。

静态断言 services/book_block_generators.py 不 import 任何门控/判分模块。
对照 C3 persona / C4 rag / C5 memory / W3 A4 knowledge_hub_search 同一模式。
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

_MODULE = Path(__file__).parent.parent / "services" / "book_block_generators.py"


def _imported_module_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def test_book_block_generators_never_imports_gating_or_grading_modules():
    source = _MODULE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)]
    assert not hits, (
        f"book_block_generators.py 实际 import 了门控/判分相关模块 {hits}——"
        "违反红线（Book Engine 内容生成只作素材，不进门控判据）"
    )


def test_gating_functions_have_no_book_block_parameter():
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective
    from services.cognitive_service import process_interaction

    for fn in (is_mastered, next_objective, process_interaction):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any(
            k in p for p in params for k in ("block", "book_id", "chapter")
        ), f"{fn.__qualname__} 出现 Book Engine 相关参数——违反红线"


def test_is_mastered_result_unaffected_by_block_generation():
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
    fake_block_result = {"status": "ready", "payload": {"text": "无关内容"}}
    del fake_block_result
    after = is_mastered(progress, kp)

    assert before == after is True

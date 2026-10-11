"""红线：Notebook / Co-Writer 永不进门控判据（同 persona / rag / memory / book_compile 模式）。

静态断言：
  · 四个模块不 import 任何门控/判分/BKT/FSRS 模块；
  · 源码里不出现任何掌握度/门控/学习事件表名（不写也不读这些表）；
并断言 is_mastered 结果不受笔记/写作建议影响。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_MODULES = [
    _ROOT / "services" / "notebook_service.py",
    _ROOT / "services" / "cowriter_service.py",
    _ROOT / "services" / "routers" / "notebooks.py",
    _ROOT / "services" / "routers" / "cowriter.py",
]

_FORBIDDEN_IMPORTS = (
    "mastery_gate",
    "gate_store",
    "math_grade",
    "verdict_guard",
    "cognitive_service",
    "process_interaction",
    "answer_match",
    "learning_event_service",
    "learner_state_service",
    "fsrs",
    "bkt",
    "practice_queue_service",
)

_FORBIDDEN_TABLES = (
    "kc_mastery",
    "mastery_snapshots",
    "interaction_events",
    "learning_events",
    "gate.",
    "memory_evidence",
    "memory_claims",
    "interaction_history",
)


def _imported_module_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def _string_literals(source: str) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_never_imports_gating_or_grading_modules(path: Path):
    imported = _imported_module_names(path.read_text(encoding="utf-8"))
    hits = sorted({f for f in _FORBIDDEN_IMPORTS for imp in imported if f in imp.lower()})
    assert not hits, f"{path.name} import 了门控/判分相关模块 {hits}（笔记/写作不进门控判据）"


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_never_touches_mastery_or_learning_event_tables(path: Path):
    source = path.read_text(encoding="utf-8")
    # docstring 里的说明性文字不算；只看非 docstring 的字符串常量（SQL 等）
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(n, clean=False)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    literals = [s for s in _string_literals(source) if s not in docstrings]
    hits = sorted({t for t in _FORBIDDEN_TABLES for s in literals if t in s})
    assert not hits, f"{path.name} 引用了掌握度/学习事件表 {hits}"


def test_is_mastered_unaffected_by_notes_and_cowriter():
    from mneme_core.oprim.mastery_gate import is_mastered
    from mneme_core.oprim.models import BktPosterior, KnowledgePoint, KnowledgeType, LearningProgress

    from services import cowriter_service as cw

    kp = KnowledgePoint(id="k1", name="k1", type=KnowledgeType.PROCEDURE)
    progress = LearningProgress(
        student_id="s1", modules=[], bkt={"k1": BktPosterior(p_learned=0.40, sigma=0.05, n_obs=3)}
    )
    before = is_mastered(progress, kp)
    # 写作建议的纯计算部分跑一遍：不应碰任何学习者状态
    d = cw.build_diff("I goes home.", "I go home.", "en")
    cw.apply_hunks("I goes home.", d["hunks"], [h["id"] for h in d["hunks"]])
    after = is_mastered(progress, kp)
    assert before == after is False

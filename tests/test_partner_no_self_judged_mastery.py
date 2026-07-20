"""W5 PA-5 红线：Partner 推送不自行判定掌握度。

静态断言 Partner 相关模块（evaluator/oskill/task）不 import 任何门控/判分
写入模块——推送只读 fsrs_due/fsrs_state 做真实信号触发（PA-3），不参与、不
替代掌握度判定（唯一路径仍是 guard）。对照 tests/test_memory_no_gating_coupling.py
同一红线测试模式。
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

_PARTNER_MODULES = (
    Path(__file__).parent.parent / "vendor" / "oprim" / "check_partner_review_due.py",
    Path(__file__).parent.parent / "vendor" / "oskill" / "partner_dispatch.py",
    Path(__file__).parent.parent / "tasks" / "partner_heartbeat.py",
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


def test_partner_modules_never_import_gating_or_grading_modules():
    for path in _PARTNER_MODULES:
        source = path.read_text(encoding="utf-8")
        imported = _imported_module_names(source)
        hits = [
            name for name in _FORBIDDEN_IMPORTS if any(name in imp for imp in imported)
        ]
        assert not hits, (
            f"{path.name} 实际 import 了门控/判分相关模块 {hits}——"
            "违反红线（Partner 推送不自行判定掌握度）"
        )


def test_partner_evaluator_only_reads_fsrs_fields_never_writes():
    """check_partner_review_due 只 SELECT，没有 INSERT/UPDATE/DELETE 写库。"""
    source = (
        Path(__file__).parent.parent
        / "vendor"
        / "oprim"
        / "check_partner_review_due.py"
    ).read_text(encoding="utf-8")
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert verb not in source.upper(), (
            f"check_partner_review_due.py 出现 {verb}——evaluator 应该只读不写"
        )

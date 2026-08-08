"""掌握度写路径守卫：单源 BKT + 禁止 mneme_core BKT 进入写库链。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 掌握度落库相关服务文件（写路径）
WRITE_PATH_GLOBS = (
    "services/cognitive_service.py",
    "services/mcp_router.py",
    "services/review_service.py",
    "services/quiz_service.py",
    "services/vocab_service.py",
    "services/socratic_service.py",
    "services/math_grade.py",
    "services/mastery_gate_service.py",
)


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def test_write_path_never_imports_mneme_core_bkt():
    """mneme_core.oprim.bkt 是另一套经典 4 参 API，禁止进入写掌握度路径。"""
    offenders: list[str] = []
    for rel in WRITE_PATH_GLOBS:
        path = ROOT / rel
        if not path.exists():
            continue
        for mod in _imports_of(path):
            if mod == "mneme_core.oprim.bkt" or mod.startswith("mneme_core.oprim.bkt."):
                offenders.append(rel)
    assert offenders == [], f"write path imports mneme_core BKT: {offenders}"


def test_process_interaction_goes_through_omodul_cognitive():
    text = (ROOT / "services" / "cognitive_service.py").read_text(encoding="utf-8")
    assert "from omodul.cognitive import" in text
    assert "process_interaction_workflow" in text


def test_cognitive_update_uses_vendor_bkt_not_mneme_core():
    text = (ROOT / "vendor" / "oskill" / "cognitive_state.py").read_text(
        encoding="utf-8"
    )
    assert "from oprim.bkt import" in text
    assert "mneme_core" not in text


def test_errortype_single_source_in_obase():
    from obase.domain_enums import ErrorType as ObaseET
    from services.models import ErrorType as ModelsET

    assert ObaseET is ModelsET
    assert {e.value for e in ObaseET} == {
        "conceptual",
        "transfer",
        "careless",
        "logic_break",
        "dontknow",
    }

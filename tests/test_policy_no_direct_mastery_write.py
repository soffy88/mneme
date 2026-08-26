import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_policy_layers_do_not_assign_to_mastery_state():
    for relative in (
        "packages/mneme-core/mneme_core/policy_engine.py",
        "services/policy_service.py",
        "services/policy_trace.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "update(KCMastery" not in source
        assert "insert(KCMastery" not in source
        assert "delete(KCMastery" not in source
        if relative != "services/policy_service.py":
            assert not any(
                isinstance(node, ast.ImportFrom)
                and node.module == "services.models"
                and any(alias.name == "KCMastery" for alias in node.names)
                for node in ast.walk(tree)
            )

"""DB-free architecture gate for the first canonical closure."""

from pathlib import Path

from scripts.architecture_gate import (
    PROJECT_ADAPTER_ALLOWLIST,
    find_forbidden_vendor_project_imports,
    validate_adapter_allowlist,
)


def test_vendor_reverse_dependencies_are_explicit_adapters_only():
    assert validate_adapter_allowlist() == []
    assert find_forbidden_vendor_project_imports() == []


def test_adapter_allowlist_is_narrow_and_documented():
    assert len(PROJECT_ADAPTER_ALLOWLIST) == 16


def test_mneme_core_cognitive_modules_are_adapters_not_algorithm_sources():
    root = Path(__file__).parents[2]
    bkt = (root / "packages/mneme-core/mneme_core/domain/oprim/bkt.py").read_text()
    spacing = (root / "packages/mneme-core/mneme_core/domain/oprim/spacing.py").read_text()
    assert "from oprim._cognitive import bkt_update" in bkt
    assert "from oprim.fsrs_engine import fsrs_new_card, fsrs_review" in spacing
    assert "Bayes' rule" not in bkt
    assert "multipliers =" not in spacing

#!/usr/bin/env python3
"""Structural boundary checks for the vendored 3O closure.

The files in ``vendor/{oprim,oskill,omodul,obase}`` are normally canonical
shared code.  A small, explicit set is retained as Mneme adapters for now
because moving their public import paths would be a behavior-changing
migration.  They are not canonical 3O and must stay on this allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOTS = tuple(
    ROOT / "vendor" / name for name in ("oprim", "oskill", "omodul", "obase")
)

# Keep this list exact and boring.  A new exception requires documentation in
# vendor/PROJECT_ADAPTERS.md and a focused test; wildcards are intentionally
# not supported.
PROJECT_ADAPTER_ALLOWLIST = frozenset(
    {
        "oskill/visualize_dispatch.py",
        "oskill/solve_dispatch.py",
        "oskill/socratic_loop.py",
        "oskill/partner_dispatch.py",
        "oskill/paper_grading.py",
        "omodul/book_compile.py",
        "omodul/visualize_concept.py",
        "omodul/solve_problem.py",
        "omodul/analyze_paper.py",
        "omodul/paper.py",
        "obase/cognitive_store.py",
        "obase/prior_provider.py",
        "oprim/answer_policy.py",
        "oprim/retrieve_chunks.py",
        "oprim/check_partner_review_due.py",
        "oprim/learner_profile_summary.py",
    }
)


def _project_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        result.extend(
            name
            for name in names
            if name == "services"
            or name.startswith("services.")
            or name == "mneme_core"
            or name.startswith("mneme_core.")
        )
    return result


def find_forbidden_vendor_project_imports() -> list[tuple[str, str]]:
    """Return direct project imports from vendor files outside the allowlist."""
    findings: list[tuple[str, str]] = []
    for root in VENDOR_ROOTS:
        for path in root.rglob("*.py"):
            rel = path.relative_to(ROOT / "vendor").as_posix()
            if rel in PROJECT_ADAPTER_ALLOWLIST:
                continue
            findings.extend((rel, module) for module in _project_imports(path))
    return sorted(findings)


def validate_adapter_allowlist() -> list[str]:
    """Return allowlisted adapter paths that disappeared or left vendor roots."""
    missing: list[str] = []
    for rel in PROJECT_ADAPTER_ALLOWLIST:
        path = ROOT / "vendor" / rel
        if not path.is_file() or path.parts[-2] not in {"oprim", "oskill", "omodul", "obase"}:
            missing.append(rel)
    return sorted(missing)


def main() -> int:
    missing = validate_adapter_allowlist()
    forbidden = find_forbidden_vendor_project_imports()
    if missing or forbidden:
        for rel in missing:
            print(f"adapter allowlist path missing: vendor/{rel}")
        for rel, module in forbidden:
            print(f"forbidden vendor project import: vendor/{rel}: {module}")
        return 1
    print(f"ok: {len(PROJECT_ADAPTER_ALLOWLIST)} explicit Mneme adapters; no shared reverse imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

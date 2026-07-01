"""Oskill — Composite financial analysis workflows built on oprim atomic operations. Lazy-loaded."""

from __future__ import annotations
import ast
import importlib
from pathlib import Path
from typing import Any
from oskill._version import __version__

_ELEMENT_MAP: dict[str, str] = {}
_SUBMODULE_SET: set[str] = set()

def _build_element_map() -> None:
    pkg_dir = Path(__file__).parent
    pkg_name = __package__ or "oskill"
    for py in sorted(pkg_dir.rglob("*.py")):
        rel_path = py.relative_to(pkg_dir)
        if rel_path.parts == ("__init__.py",): continue
        mod_parts = list(rel_path.with_suffix("").parts)
        if mod_parts[-1] == "__init__": mod_parts.pop()
        if not mod_parts: continue
        mod_path = pkg_name + "." + ".".join(mod_parts)
        stem = mod_parts[-1]
        _SUBMODULE_SET.add(stem)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in tree.body:
                names = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.ImportFrom) and rel_path.name == "__init__.py":
                    for alias in node.names:
                        if alias.name != "*": names.append(alias.asname or alias.name)
                for name in names:
                    if not name.startswith("_"):
                        # Heuristic: prefer non-prefixed modules, or if mapping to private, allow overwrite by public
                        if name not in _ELEMENT_MAP or (
                            not mod_path.split(".")[-1].startswith("_") and _ELEMENT_MAP[name].split(".")[-1].startswith("_")
                        ):
                            _ELEMENT_MAP[name] = mod_path
        except Exception: continue

_build_element_map()

def __getattr__(name: str) -> Any:
    if name == "__version__": return __version__
    if name in _ELEMENT_MAP:
        mod = importlib.import_module(_ELEMENT_MAP[name])
        # Special case for FusedResult/SearchResult aliases in merge_platform_user_results
        actual_name = name
        if name == "MergedFusedResult": actual_name = "FusedResult"
        if name == "MergedSearchResult": actual_name = "SearchResult"
        return getattr(mod, actual_name)
    if name in _SUBMODULE_SET:
        pkg_name = __package__ or "oskill"
        return importlib.import_module(f"{pkg_name}.{name}")
    raise AttributeError(f"module '{__name__}' has no attribute {name!r}")

def __dir__() -> list[str]:
    return sorted(set(list(_ELEMENT_MAP.keys()) + list(_SUBMODULE_SET) + ["__version__"]))

__all__ = sorted(_ELEMENT_MAP.keys())

# --- Explicit re-exports (Pinning) ---
from oskill._types import (
    OskillError, EditOskillError, ParseOskillError, LLMOskillError, ConfigOskillError,
    EditBlock, ApplyResult, Chunk, Symbol, RepoFile, RepoMap, TodoItem, SubTask, ToolCall,
    PluginManifest, UndoPlan, HookCmd
)
from oskill._apply_edit_block import apply_edit_block
from oskill._apply_unified_diff import apply_unified_diff
from oskill._select_tools import select_tools
from oskill._select_skill import select_skill
from oskill._plan_decompose import plan_decompose
from oskill._plan_to_todos import plan_to_todos
from oskill._apply_todo_update import apply_todo_update
from oskill._summarize_file import summarize_file
from oskill._chunk_code import chunk_code
from oskill._extract_symbols import extract_symbols
from oskill._repo_map_build import repo_map_build
from oskill._rank_relevant_files import rank_relevant_files
from oskill._build_repo_context import build_repo_context
from oskill._semantic_search import semantic_search
from oskill._syntax_check import syntax_check
from oskill._validate_edit import validate_edit
from oskill._dedup_edits import dedup_edits
from oskill._generate_patch_preview import generate_patch_preview
from oskill._build_undo_plan import build_undo_plan
from oskill._format_diagnostics import format_diagnostics
from oskill.socratic_guide_v2 import socratic_guide_v2, SocraticStateV2
from oskill.metacog_scaffold import metacog_scaffold
from oskill.cold_start_single import cold_start_single
from oskill.variant_for_review import variant_for_review
from oskill.essay_guide import essay_guide
from oskill._parse_llm_tool_calls import parse_llm_tool_calls
from oskill._merge_config import merge_config
from oskill._evaluate_hooks import evaluate_hooks
from oskill._match_permission_rule import match_permission_rule
from oskill._escalate_thinking_budget import escalate_thinking_budget
from oskill._compose_plugin_manifest import compose_plugin_manifest
from oskill._build_subagent_prompt import build_subagent_prompt
from oskill._merge_subagent_result import merge_subagent_result
from oskill._compress_context import compress_context
from oskill._resolve_mentions import resolve_mentions
from oskill._resolve_memory_hierarchy import resolve_memory_hierarchy
from oskill._load_skill_progressive import load_skill_progressive
from oskill._three_way_merge import three_way_merge

from oskill._physics_force_analysis_guide import physics_force_analysis_guide, ForceAnalysisResult
from oskill._reading_comprehension_guide import reading_comprehension_guide, ReadingGuideResult
# ── AII Graph Capability (K-G1 … K-G5) ──────────────────────────────────────
# K-G1: LLM-confirmed conflict resolution (grade hardcoded unverified)
from oskill._conflict_resolution import conflict_resolution
# K-G2: two-pass CoT knowledge extraction (analyze → generate, no free-play)
from oskill._two_step_ingest import two_step_ingest
# K-G3: composite KU relevance scoring (direct/source/adamic/type weights)
from oskill._relevance_compute import relevance_compute
# K-G4: BFS graph expansion with relevance pruning
from oskill._graph_expand_retrieval import graph_expand_retrieval
# K-G5: safe cascade delete (dry_run=True default; shared KUs preserved)
from oskill._cascade_delete import cascade_delete

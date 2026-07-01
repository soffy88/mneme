"""Oprim — atomic operations library (Layer 1 meta-primitives). Lazy-loaded."""

from __future__ import annotations
import ast
import importlib
from pathlib import Path
from typing import Any
from oprim._version import __version__

_ELEMENT_MAP: dict[str, str] = {}
_SUBMODULE_SET: set[str] = set()

def _build_element_map() -> None:
    pkg_dir = Path(__file__).parent
    pkg_name = __package__ or "oprim"
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
                        if name not in _ELEMENT_MAP or (
                            not mod_path.split(".")[-1].startswith("_") and _ELEMENT_MAP[name].split(".")[-1].startswith("_")
                        ):
                            _ELEMENT_MAP[name] = mod_path
        except Exception: continue

_build_element_map()

from oprim._cognitive import KCState  # re-export for oskill compatibility
# llm_summarize 惰性加载（依赖 obase，不在没有 obase 的环境 eager-load）
def llm_summarize(*args, **kwargs):
    """惰性加载 llm_summarize，调用时才 import obase 依赖。"""
    from oprim._llm_summarize import llm_summarize as _fn
    return _fn(*args, **kwargs)

def __getattr__(name: str) -> Any:
    if name == "__version__": return __version__
    if name in _ELEMENT_MAP:
        mod = importlib.import_module(_ELEMENT_MAP[name])
        return getattr(mod, name)
    if name in _SUBMODULE_SET:
        pkg_name = __package__ or "oprim"
        return importlib.import_module(f"{pkg_name}.{name}")
    raise AttributeError(f"module '{__name__}' has no attribute {name!r}")

def __dir__() -> list[str]:
    return sorted(set(list(_ELEMENT_MAP.keys()) + list(_SUBMODULE_SET) + ["__version__"]))

__all__ = sorted(_ELEMENT_MAP.keys())

# --- Explicit re-exports (Pinning) ---
from oprim._exceptions import (
    OprimError, FileOprimError, GitOprimError, ShellOprimError,
    ParseOprimError, PathSecurityError, LLMOprimError, BudgetExceededError,
    PromptOprimError, SearchOprimError, HttpOprimError, SnapshotOprimError
)
from oprim.llm._types import (
    LLMResponse, StreamDelta, EmbedResult, ConversationSnapshot,
    ThinkingResult, SearchResult, HttpResponse
)
# llm_complete: 惰性加载（依赖 obase）
def llm_complete(*args, **kwargs):
    from oprim.llm._llm_complete import llm_complete as _fn
    return _fn(*args, **kwargs)
def llm_stream(*args, **kwargs):
    from oprim.llm._llm_stream import llm_stream as _fn
    return _fn(*args, **kwargs)
def embed_text(*args, **kwargs):
    from oprim.llm._embed_text import embed_text as _fn
    return _fn(*args, **kwargs)
from oprim.prompt import (
    build_system_prompt, truncate_messages, extract_thinking, snapshot_conversation
)
def image_generate(*args, **kwargs):
    from oprim.image_generate import image_generate as _fn
    return _fn(*args, **kwargs)
def image_understand(*args, **kwargs):
    from oprim.image_understand import image_understand as _fn
    return _fn(*args, **kwargs)
def tts_synthesize(*args, **kwargs):
    from oprim.tts_synthesize import tts_synthesize as _fn
    return _fn(*args, **kwargs)

# --- Mneme elements (M-A batch) ---
from oprim.types import (
    SolveResult, SolveStep, StepCheckResult, Plot2DData, Three3DData,
    GradeResult, PeerPercentileResult
)
from oprim.compute_peer_percentile import compute_peer_percentile, compute_percentile_batch
from oprim.recognition_update import recognition_update, recognition_update_sequence
from oprim.compute_effortful_gain import compute_effortful_gain, compute_effortful_gain_from_arrays
from oprim.compute_feedback import compute_feedback, grade_answer
from oprim.file_type_detector import file_type_detector as file_type_detector
from oprim.due_compute import due_compute
from oprim.speech_to_math import speech_to_math
from oprim.error_classify import error_classify

# File parsers + structure extractor (restored exports)
def file_parser_pdf(*args, **kwargs):
    from oprim._file_parser_pdf import file_parser_pdf as _fn
    return _fn(*args, **kwargs)
def file_parser_epub(*args, **kwargs):
    from oprim._file_parser_epub import file_parser_epub as _fn
    return _fn(*args, **kwargs)
def file_parser_html(*args, **kwargs):
    from oprim._file_parser_html import file_parser_html as _fn
    return _fn(*args, **kwargs)
# from oprim._file_parser_markdown import file_parser_markdown as file_parser_markdown
from oprim._file_parser_plaintext import file_parser_plaintext as file_parser_plaintext
from oprim._document_structure_extractor import document_structure_extractor as document_structure_extractor

def epub_toc_split(*args, **kwargs):
    from oprim._epub_toc_split import epub_toc_split as _fn
    return _fn(*args, **kwargs)
def _get_EpubBook():
    from oprim._epub_toc_split import EpubBook
    return EpubBook
from oprim._markdown_frontmatter_build import markdown_frontmatter_build
from oprim._text_clean_publish_noise import text_clean_publish_noise
from oprim._arxiv_search import arxiv_search, ArxivPaper
from oprim._http_download_file import http_download_file
from oprim._media_types import SourceResult
from oprim._gutenberg_search import gutenberg_search
from oprim._oapen_search import oapen_search
# ── AII Graph Capability (P-G1 … P-G7) ──────────────────────────────────────
# Types (shared across AII graph elements)
from oprim._aii_graph_types import (
    ConflictSignal,
    ConflictPair,
    SourceTraceResult,
    GraphRetrievalResult,
    CascadeDeleteResult,
    TwoStepIngestResult,
    ConflictDetectionInput,
)
# P-G1: conflict candidate detection (pure computation, no LLM)
from oprim._ku_conflict_detect import ku_conflict_detect
# P-G2: purpose alignment scoring (cosine + keyword, no LLM)
from oprim._purpose_alignment_score import purpose_alignment_score
# P-G3: source provenance query (single async DB call)
from oprim._source_trace import source_trace
# P-G4: direct graph link score
from oprim._direct_link_score import direct_link_score
# P-G5: shared source overlap score
from oprim._source_overlap_score import source_overlap_score
# P-G6: adamic-adar similarity score
from oprim._adamic_adar_score import adamic_adar_score
# P-G7: knowledge-type affinity score
from oprim._type_affinity_score import type_affinity_score

from oprim._quant_analysis import compute_shapley_decomposition, compute_shapley_values

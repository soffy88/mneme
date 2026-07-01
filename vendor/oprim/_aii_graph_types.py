"""Shared graph relation types for AII deep-understanding batch.

Used across oprim (P-AII-3), oskill (K-AII-3/4), and omodul (M-AII-3/4).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RelationCandidate:
    """Result of rule-based relation extraction (P-AII-3)."""
    relation_type: str   # special_case_of/prerequisite_of/basis_of/references/contradicts
    target_ref: str      # target KU name or ID
    evidence: str        # matched pattern / evidence string for traceability
    confidence_signal: str  # "rule_match"|"symbol_dep"|"citation"|"ambiguous"


@dataclass
class RelationResult:
    """Result of LLM-based relation extraction (K-AII-3).

    grade is hardcoded to "unverified" — not settable by callers.
    """
    relation_type: str
    direction: str       # "a_to_b"|"b_to_a"|"bidirectional"
    rationale: str
    grade: str = field(init=False)

    def __post_init__(self) -> None:
        self.grade = "unverified"


@dataclass
class Community:
    """One community produced by community_cluster (K-AII-4)."""
    label: str              # representative ku_id or auto label
    ku_ids: list[str]
    centroid: list[float]   # centroid vector
    size: int


@dataclass
class SummarySynthesizeInput:
    """Input for summary_synthesize (M-AII-3)."""
    ku_ids: list[str]
    ku_texts: list[str]
    source_grades: list[str]


@dataclass
class BookUnderstandingInput:
    """Input for book_understanding_synthesize (M-AII-4)."""
    ku_ids: list[str]
    ku_texts: list[str]
    ku_grades: list[str]


@dataclass
class TheoremVerifyResult:
    """Result of three-way theorem verification (K-AII-5).

    verdict: "verified" | "rejected" | "ambiguous"
    lean_name and type_signature are populated only when verdict=="verified".
    Both come exclusively from mathlib_lookup, never from LLM output.
    """
    verdict: str              # "verified" | "rejected" | "ambiguous"
    lean_name: str | None     # only set when verified
    type_signature: str | None  # only set when verified
    reason: str               # rejection/ambiguity reason; "" when verified


@dataclass
class ConflictSignal:
    """Output of ku_conflict_detect (P-G1)."""
    is_conflict_candidate: bool
    similarity: float
    polarity_signal: str   # "opposing"|"neutral"|"insufficient"
    evidence: str          # matched polarity pair, traceable


@dataclass
class ConflictPair:
    """One confirmed conflict pair from conflict_resolution (K-G1).

    grade is hardcoded "unverified" — not settable by callers.
    """
    new_ku_idx: int
    existing_ku_id: str
    conflict_type: str    # "factual_contradiction"|"stance_opposition"|"scope_conflict"
    description: str
    severity: str         # "high"|"medium"|"low"
    grade: str = field(init=False)

    def __post_init__(self) -> None:
        self.grade = "unverified"


@dataclass
class SourceTraceResult:
    """Output of source_trace (P-G3)."""
    ku_id: str
    source_ids: list[str]
    source_positions: list[dict]   # [{source_id, page, chunk_idx, text_snippet}]
    trace_depth: int


@dataclass
class GraphRetrievalResult:
    """One result from graph_expand_retrieval (K-G4)."""
    ku_id: str
    score: float
    hop_distance: int
    retrieval_path: list[str]   # path from seed to this KU


@dataclass
class CascadeDeleteResult:
    """Output of cascade_delete (K-G5)."""
    deleted_ku_ids: list[str]      # KUs only supported by this source (deleted or would-delete)
    preserved_ku_ids: list[str]    # multi-source shared KUs (kept)
    dangling_deps_cleared: int     # dangling dependency references cleared
    dry_run: bool


@dataclass
class TwoStepIngestResult:
    """Output of two_step_ingest (K-G2)."""
    analysis: dict              # Step 1: entities/concepts/conflict candidates/structure
    ku_candidates: list[dict]   # Step 2: generated KU candidates
    conflict_candidates: list[str]  # conflict descriptions (pending conflict_resolution)


@dataclass
class ConflictDetectionInput:
    """Input for conflict_detection_workflow (M-G1)."""
    new_ku_texts: list[str]
    new_ku_embeddings: list[list[float]]
    existing_ku_texts: list[str]
    existing_ku_embeddings: list[list[float]]
    existing_ku_ids: list[str]


# ---------------------------------------------------------------------------
# Controlled vocabularies (K-ONT-1 / M-ONT-1)
# ---------------------------------------------------------------------------

VALID_KNOWLEDGE_TYPES: frozenset[str] = frozenset([
    "factual", "conceptual", "positional", "procedural",
    "explanatory", "metacognitive",
])

VALID_RELATION_TYPES: frozenset[str] = frozenset([
    "explains", "causes", "subsumes", "special_case_of",
    "prerequisite_of", "contrasts_with", "opposes",
    "contradicts", "supported_by", "same_as",
])

VALID_GRADES: frozenset[str] = frozenset([
    "unverified", "verified", "refuted", "high",
    "moderate", "low", "contradicted", "pending",
])

VALID_SUB_TYPES: frozenset[str] = frozenset([
    "classification", "principle", "theory",
    "skill", "technique", "conditional",
    "strategic", "task_knowledge", "self_knowledge",
])


# ---------------------------------------------------------------------------
# ONT types (K-ONT-1 / M-ONT-1)
# ---------------------------------------------------------------------------

@dataclass
class OntologyExtractResult:
    """Output of ontology_extract (K-ONT-1)."""
    outline: dict                    # Pass-1: full-book outline
    ku_candidates: list[dict]        # Pass-2: 6-class KU candidates (all fields)
    edge_candidates: list[dict]      # relation candidates (controlled relation_type)
    concept_candidates: list[str]    # concept candidates
    stats: dict                      # {total, by_type, explains_count}


@dataclass
class RegisterKuOntologyInput:
    """Input for register_ku_ontology (M-ONT-1)."""
    ku: dict               # 6-class KU with all fields
    edges: list[dict]      # edge candidates [{source, target, relation_type}]

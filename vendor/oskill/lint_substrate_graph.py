from __future__ import annotations

from pydantic import BaseModel


class SubstrateRef(BaseModel):
    id: str
    medium: str = ""
    derivative_ids: list[str] = []
    concept_ids: list[str] = []


class DerivativeRef(BaseModel):
    id: str
    parent_substrate_id: str


class NoteRef(BaseModel):
    id: str
    substrate_refs: list[str] = []
    concept_refs: list[str] = []
    content_refs: list[str] = []


class ConceptRef(BaseModel):
    id: str
    substrate_refs: list[str] = []
    related_concept_ids: list[str] = []


class BrokenLink(BaseModel):
    source_id: str
    target_id: str
    ref_type: str


class LintReport(BaseModel):
    orphans: list[str]
    broken_links: list[BrokenLink]
    stale_concepts: list[str]
    health_score: float
    suggestions: list[str]


def lint_substrate_graph(
    *,
    substrates: list[SubstrateRef],
    derivatives: list[DerivativeRef],
    notes: list[NoteRef],
    concepts: list[ConceptRef],
) -> LintReport:
    """Validate the in-memory substrate reference graph for integrity.

    Internal oskill composition: pure graph traversal algorithm (no oprim calls).

    Checks:
        - Orphan substrates: substrates with no derivatives referencing them
        - Broken links: derivative/note/concept refs pointing to non-existent IDs
        - Stale concepts: concepts with no substrate associations

    Args:
        substrates: All substrate nodes
        derivatives: All derivative nodes
        notes: All note nodes
        concepts: All concept nodes

    Returns:
        LintReport with health score (0-100) and issue lists

    Example:
        >>> report = lint_substrate_graph(substrates=[], derivatives=[], notes=[], concepts=[])
        >>> report.health_score
        100.0
    """
    substrate_ids = {s.id for s in substrates}
    concept_ids = {c.id for c in concepts}

    broken_links: list[BrokenLink] = []

    # Check derivative → substrate refs
    referenced_substrate_ids: set[str] = set()
    for d in derivatives:
        if d.parent_substrate_id not in substrate_ids:
            broken_links.append(
                BrokenLink(
                    source_id=d.id,
                    target_id=d.parent_substrate_id,
                    ref_type="derivative_to_substrate",
                )
            )
        else:
            referenced_substrate_ids.add(d.parent_substrate_id)

    # Check note refs
    for n in notes:
        for ref in n.substrate_refs:
            if ref not in substrate_ids:
                broken_links.append(
                    BrokenLink(source_id=n.id, target_id=ref, ref_type="note_to_substrate")
                )
        for ref in n.concept_refs:
            if ref not in concept_ids:
                broken_links.append(
                    BrokenLink(source_id=n.id, target_id=ref, ref_type="note_to_concept")
                )

    # Check concept refs
    concept_referenced_substrates: set[str] = set()
    for c in concepts:
        for ref in c.substrate_refs:
            if ref not in substrate_ids:
                broken_links.append(
                    BrokenLink(source_id=c.id, target_id=ref, ref_type="concept_to_substrate")
                )
            else:
                concept_referenced_substrates.add(ref)
        for ref in c.related_concept_ids:
            if ref not in concept_ids:
                broken_links.append(
                    BrokenLink(source_id=c.id, target_id=ref, ref_type="concept_to_concept")
                )

    # Orphans: substrates not referenced by any derivative or concept
    all_referenced = referenced_substrate_ids | concept_referenced_substrates
    orphans = [s.id for s in substrates if s.id not in all_referenced]

    # Stale concepts: no substrate associations
    stale_concepts = [c.id for c in concepts if not c.substrate_refs]

    # Health score: penalize broken links and stale concepts (orphans are informational)
    total_issues = len(broken_links) + len(stale_concepts)
    total_nodes = max(1, len(substrates) + len(derivatives) + len(notes) + len(concepts))
    health_score = max(0.0, 100.0 * (1.0 - total_issues / total_nodes))

    suggestions: list[str] = []
    if orphans:
        suggestions.append(
            f"{len(orphans)} orphan substrate(s): link to concepts or create derivatives"
        )
    if broken_links:
        suggestions.append(f"{len(broken_links)} broken reference(s): remove or repair")
    if stale_concepts:
        suggestions.append(f"{len(stale_concepts)} stale concept(s): associate with substrates")

    return LintReport(
        orphans=orphans,
        broken_links=broken_links,
        stale_concepts=stale_concepts,
        health_score=round(health_score, 1),
        suggestions=suggestions,
    )

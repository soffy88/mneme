"""oprim.coherence_compute — deterministic coherence evidence computation.

3O layer: oprim (single atomic call, pure logic, no LLM, A20 compliant).
Extracted from omodul.knowledge_reflux for composable reuse.
Computes which KU nodes are supported/contradicted by confirmed knowledge.
"""

from __future__ import annotations

INDEPENDENT_SOURCES = {"formal_proof", "reproducible_empirical", "weak_empirical"}
GRADE_LADDER = ["unverified", "very_low", "low", "moderate", "high", "proven"]
SOURCE_CEILING = {
    "formal_proof": "proven",
    "reproducible_empirical": "high",
    "weak_empirical": "low",
}


def _grade_index(g: str) -> int:
    return GRADE_LADDER.index(g) if g in GRADE_LADDER else 0


def _status_of(node: dict) -> dict:
    """取节点的 completeness 子结构（缺则视为 unverified/无独立来源）。"""
    es = (node or {}).get("epistemic_status", {})
    c = es.get("completeness", {}) if isinstance(es, dict) else {}
    return {
        "grade": c.get("grade", "unverified"),
        "source": c.get("source"),
        "defeaters": list(c.get("defeaters", [])),
    }


def coherence_compute(
    *,
    nodes: dict[str, dict],
    edges: list[tuple[str, str, str]],
) -> dict[str, dict]:
    """Compute coherence evidence for each node from confirmed knowledge sources.

    Returns {node_id: {supports_from_confirmed, contradicts_from_confirmed, supporters, contradictors}}
    Only counts edges from confirmed knowledge (grade >= moderate + independent source).
    """
    confirmed = set()
    for nid, node in nodes.items():
        st = _status_of(node)
        if st["source"] in INDEPENDENT_SOURCES and _grade_index(st["grade"]) >= _grade_index(
            "moderate"
        ):
            confirmed.add(nid)

    coh = {
        nid: {
            "supports_from_confirmed": 0,
            "contradicts_from_confirmed": 0,
            "supporters": [],
            "contradictors": [],
        }
        for nid in nodes
    }
    for s, r, d in edges:
        if d not in coh:
            continue
        if r == "supports" and s in confirmed:
            coh[d]["supports_from_confirmed"] += 1
            coh[d]["supporters"].append(s)
        elif r == "contradicts" and s in confirmed:
            coh[d]["contradicts_from_confirmed"] += 1
            coh[d]["contradictors"].append(s)
    return coh

"""P-G4: direct_link_score — count direct edges between two KUs.

Score = min(count * 3.0, 9.0). Pure computation.
"""
from __future__ import annotations


def direct_link_score(
    *,
    ku_id_a: str,
    ku_id_b: str,
    edges: list[dict],
) -> float:
    """Score based on direct edges between ku_id_a and ku_id_b.

    Counts both a→b and b→a edges. Max score 9.0 (3 edges × 3.0).
    """
    count = 0
    for edge in edges:
        src = edge.get("source") or edge.get("src") or edge.get("from", "")
        tgt = edge.get("target") or edge.get("tgt") or edge.get("to", "")
        if (src == ku_id_a and tgt == ku_id_b) or (src == ku_id_b and tgt == ku_id_a):
            count += 1
    return min(count * 3.0, 9.0)

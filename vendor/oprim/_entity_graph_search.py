"""oprim.entity_graph_search — single graph traversal from seed nodes.

3O layer: oprim (single atomic call, pure BFS traversal, no LLM).
Cross-business reusable: traverses edges N hops from seeds, ranks by visit frequency.
GraphRAG advantage: finds related nodes via explicit relations (not just vectors).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable


def entity_graph_search(
    *,
    seed_ids: list[str],
    list_edges: Callable,
    hops: int = 1,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Traverse knowledge graph from seed nodes N hops, return ranked neighbors.

    list_edges: callable(node_id) -> list of edge objects with .dst_id attribute
    Returns [(node_id, score)] sorted by score descending, excluding seeds.
    """
    freq: dict[str, float] = defaultdict(float)
    frontier = list(seed_ids)
    seen = set(seed_ids)
    for h in range(hops):
        nxt = []
        decay = 1.0 / (h + 1)
        for nid in frontier:
            for e in list_edges(nid):
                freq[e.dst_id] += decay
                if e.dst_id not in seen:
                    seen.add(e.dst_id)
                    nxt.append(e.dst_id)
        frontier = nxt
    # exclude seeds from results
    result = {k: v for k, v in freq.items() if k not in set(seed_ids)}
    return sorted(result.items(), key=lambda x: -x[1])[:top_k]

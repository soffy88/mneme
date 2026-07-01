"""P-G6: adamic_adar_score — Adamic-Adar link prediction index × 1.5.

Skips common neighbors with degree ≤ 1 (log(1) = 0). Pure computation.
"""
from __future__ import annotations

import math


def adamic_adar_score(
    *,
    neighbors_a: list[str],
    neighbors_b: list[str],
    neighbor_degree: dict[str, int],
) -> float:
    """Adamic-Adar index × 1.5 over common neighbors.

    Nodes with degree ≤ 1 are skipped (log would be 0 or negative).
    """
    common = set(neighbors_a) & set(neighbors_b)
    total = 0.0
    for node in common:
        deg = neighbor_degree.get(node, 0)
        if deg <= 1:
            continue
        total += 1.0 / math.log(deg)
    return total * 1.5

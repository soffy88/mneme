"""oprim.build_q_matrix — Build Q-matrix from knowledge graph 'assesses' edges.

3O layer: oprim (single atomic construction, pure logic, no LLM).
Q-matrix[item, skill] = 1 if item 'assesses' skill, else 0.
Used by cognitive_diagnosis for DINA model.
"""

from __future__ import annotations
import numpy as np


def build_q_matrix(
    *,
    edges: list[tuple[str, str, str]],
    item_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict:
    """Build Q-matrix from (src, 'assesses', dst) edges.

    edges: list of (src_id, relation, dst_id) tuples
    item_ids: explicit ordering (inferred from edges if None)
    skill_ids: explicit ordering (inferred from edges if None)

    Returns: {
        Q: np.ndarray of shape (n_items, n_skills),
        item_ids: list[str],
        skill_ids: list[str],
        item_index: dict[str, int],
        skill_index: dict[str, int],
    }
    """
    # Filter to 'assesses' edges only
    assesses = [(s, d) for s, r, d in edges if r == "assesses"]

    # Infer item_ids / skill_ids if not provided
    if item_ids is None:
        seen = dict.fromkeys(s for s, _ in assesses)
        item_ids = list(seen)
    if skill_ids is None:
        seen = dict.fromkeys(d for _, d in assesses)
        skill_ids = list(seen)

    n_items = len(item_ids)
    n_skills = len(skill_ids)
    Q = np.zeros((n_items, n_skills), dtype=np.int8)

    item_index = {iid: i for i, iid in enumerate(item_ids)}
    skill_index = {sid: i for i, sid in enumerate(skill_ids)}

    for s, d in assesses:
        if s in item_index and d in skill_index:
            Q[item_index[s], skill_index[d]] = 1

    return {
        "Q": Q,
        "item_ids": item_ids,
        "skill_ids": skill_ids,
        "item_index": item_index,
        "skill_index": skill_index,
    }

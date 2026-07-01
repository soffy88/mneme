"""P-G7: type_affinity_score — KU type affinity lookup.

Default matrix: same=1.0, theorem↔definition=0.8, example↔theorem=0.6, other=0.2.
Custom affinity_matrix can override defaults. Pure computation.
"""
from __future__ import annotations

_DEFAULT_AFFINITY: dict[tuple[str, str], float] = {
    ("theorem", "theorem"): 1.0,
    ("definition", "definition"): 1.0,
    ("example", "example"): 1.0,
    ("lemma", "lemma"): 1.0,
    ("corollary", "corollary"): 1.0,
    ("theorem", "definition"): 0.8,
    ("definition", "theorem"): 0.8,
    ("theorem", "lemma"): 0.9,
    ("lemma", "theorem"): 0.9,
    ("example", "theorem"): 0.6,
    ("theorem", "example"): 0.6,
    ("example", "definition"): 0.5,
    ("definition", "example"): 0.5,
}

_DEFAULT_SAME_TYPE = 1.0
_DEFAULT_OTHER = 0.2


def type_affinity_score(
    *,
    type_a: str,
    type_b: str,
    affinity_matrix: dict[str, dict[str, float]] | None = None,
) -> float:
    """Return affinity score between two KU types (0.0–1.0).

    Custom affinity_matrix format: {type_a: {type_b: score}}.
    Falls back to built-in defaults when not found in custom matrix.
    """
    if affinity_matrix is not None:
        row = affinity_matrix.get(type_a, {})
        if type_b in row:
            return float(row[type_b])
        # try reverse
        row_r = affinity_matrix.get(type_b, {})
        if type_a in row_r:
            return float(row_r[type_a])

    if type_a == type_b:
        return _DEFAULT_SAME_TYPE
    return _DEFAULT_AFFINITY.get((type_a, type_b), _DEFAULT_OTHER)

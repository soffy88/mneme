"""P-G5: source_overlap_score — Jaccard similarity × 4.

Pure computation. Empty sets → 0.
"""
from __future__ import annotations


def source_overlap_score(
    *,
    sources_a: list[str],
    sources_b: list[str],
) -> float:
    """Jaccard similarity of source sets × 4.

    Returns 0.0 if both sets are empty.
    """
    sa = set(sources_a)
    sb = set(sources_b)
    union = sa | sb
    if not union:
        return 0.0
    return (len(sa & sb) / len(union)) * 4.0

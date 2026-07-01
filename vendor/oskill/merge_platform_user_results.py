from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class SearchResult:
    id: str
    type: str
    title: str
    score: float
    highlight: str | None = None
    is_pinned: bool = False
    metadata: dict = field(default_factory=dict)  # type: ignore[type-arg]


class FusedResult(BaseModel):
    id: str
    type: str
    title: str
    score: float
    highlight: str | None
    is_pinned: bool
    source: str  # "platform" | "user"


def merge_platform_user_results(
    *,
    platform_results: list[SearchResult],
    user_results: list[SearchResult],
    k: int = 60,
    pinned_boost: float = 1.5,
) -> list[FusedResult]:
    """Fuse platform and user search results using Reciprocal Rank Fusion (RRF).

    Internal oskill composition: pure RRF algorithm (no oprim calls).

    Algorithm (v0.6 P3 spec):
        score(id) = sum of 1/(k + rank) across all result lists
        pinned user items get their RRF contribution multiplied by pinned_boost

    Args:
        platform_results: Ordered platform search results (rank 0 = best)
        user_results: Ordered user search results (rank 0 = best)
        k: RRF smoothing constant (default 60)
        pinned_boost: Score multiplier for is_pinned user items

    Returns:
        Merged list sorted by RRF score descending

    Example:
        >>> results = merge_platform_user_results(
        ...     platform_results=[SearchResult(id="p1", type="doc", title="T", score=1.0)],
        ...     user_results=[SearchResult(id="u1", type="note", title="U", score=1.0,
        ...                               is_pinned=True)],
        ...     pinned_boost=2.0,
        ... )
    """
    if not platform_results and not user_results:
        return []

    rrf_scores: dict[str, float] = {}
    item_map: dict[str, tuple[SearchResult, str]] = {}

    for rank, item in enumerate(platform_results):
        rrf_scores[item.id] = rrf_scores.get(item.id, 0.0) + 1.0 / (k + rank + 1)
        item_map[item.id] = (item, "platform")

    for rank, item in enumerate(user_results):
        s = 1.0 / (k + rank + 1)
        if item.is_pinned:
            s *= pinned_boost
        rrf_scores[item.id] = rrf_scores.get(item.id, 0.0) + s
        # user entry overwrites platform source for same id
        item_map[item.id] = (item, "user")

    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    results: list[FusedResult] = []
    for id_ in sorted_ids:
        item, source = item_map[id_]
        results.append(
            FusedResult(
                id=item.id,
                type=item.type,
                title=item.title,
                score=rrf_scores[id_],
                highlight=item.highlight,
                is_pinned=item.is_pinned,
                source=source,
            )
        )

    return results

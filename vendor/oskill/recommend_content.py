"""Recommend platform content based on user behavior and content metadata."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from pydantic import BaseModel


class UserBehaviorProfile(BaseModel):
    recent_viewed: list[str] = []
    bookmarked: list[str] = []
    high_density_content: list[str] = []
    mentioned_concepts: list[str] = []
    subscribed_domains: list[str] = []


class ContentMeta(BaseModel):
    content_id: str
    title: str
    domain: list[str] = []
    tags: list[str] = []
    related_concept_ids: list[str] = []
    published_at: datetime
    embedding: list[float] | None = None


class Recommendation(BaseModel):
    content_id: str
    title: str
    score: float  # 0-1
    reason: str


def recommend_content(
    *,
    user_profile: UserBehaviorProfile,
    candidate_pool: list[ContentMeta],
    top_k: int = 10,
    recency_weight: float = 0.3,
    relevance_weight: float = 0.7,
) -> list[Recommendation]:
    """Recommend platform content based on user behavior and content metadata.

    Internal oskill composition:
        - Pure relevance scoring: domain/tag/concept overlap with user profile
        - Pure recency scoring: time decay on published_at
        - Weighted score combination

    Args:
        user_profile: User behavior signals
        candidate_pool: Content items to rank
        top_k: Number of recommendations to return
        recency_weight: Weight for recency score [0, 1]
        relevance_weight: Weight for relevance score [0, 1]

    Returns:
        List of Recommendation sorted by score descending

    Example:
        >>> from datetime import datetime, timezone
        >>> profile = UserBehaviorProfile()
        >>> pool = [ContentMeta(content_id="c1", title="AI",
        ...     published_at=datetime.now(timezone.utc), domain=["AI"])]
        >>> recs = recommend_content(user_profile=profile, candidate_pool=pool, top_k=1)
        >>> len(recs) == 1
        True
    """
    if not candidate_pool:
        return []

    # Normalize weights
    total_w = recency_weight + relevance_weight
    if total_w > 0:
        rec_w = recency_weight / total_w
        rel_w = relevance_weight / total_w
    else:
        rec_w, rel_w = 0.5, 0.5

    user_has_behavior = bool(
        user_profile.recent_viewed
        or user_profile.bookmarked
        or user_profile.subscribed_domains
        or user_profile.mentioned_concepts
    )

    now = datetime.now(UTC)
    scored: list[tuple[float, ContentMeta, str]] = []

    for content in candidate_pool:
        # Skip already viewed
        if content.content_id in user_profile.recent_viewed:
            continue

        # Recency score: exponential decay, half-life 30 days
        pub = content.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        age_days = max(0.0, (now - pub).total_seconds() / 86400)
        recency_score = math.exp(-age_days / 30.0)

        if not user_has_behavior:
            # No behavior: rank purely by recency
            score = recency_score
            reason = "new in your feed"
        else:
            # Relevance score: domain/concept overlap
            domain_overlap = len(set(content.domain) & set(user_profile.subscribed_domains))
            concept_overlap = len(
                set(content.related_concept_ids) & set(user_profile.mentioned_concepts)
            )
            bookmark_bonus = 0.3 if content.content_id in user_profile.bookmarked else 0.0

            relevance_score = min(
                1.0,
                (domain_overlap * 0.4 + concept_overlap * 0.3 + bookmark_bonus) / 1.0,
            )
            score = rec_w * recency_score + rel_w * relevance_score

            # Reason
            if domain_overlap > 0:
                reason = f"new in {content.domain[0]}"
            elif concept_overlap > 0:
                reason = "related to concept you noted"
            else:
                reason = "based on your reading"

        scored.append((score, content, reason))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        Recommendation(
            content_id=c.content_id,
            title=c.title,
            score=round(s, 4),
            reason=r,
        )
        for s, c, r in scored[:top_k]
    ]

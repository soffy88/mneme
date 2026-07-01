"""P-G2: purpose_alignment_score — cosine similarity + keyword overlap weighted score.

Pure computation, no LLM. Score range 0.0–1.0.
"""
from __future__ import annotations

import re


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _keyword_tokens(text: str) -> set[str]:
    """Extract keyword tokens: CJK bigrams + lowercased English words."""
    tokens: set[str] = set()
    # CJK bigrams
    cjk = re.findall(r"[一-鿿]", text)
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i] + cjk[i + 1])
    # English words
    for word in re.findall(r"[a-zA-Z]{2,}", text):
        tokens.add(word.lower())
    return tokens


def _keyword_overlap(text_a: str, text_b: str) -> float:
    sa = _keyword_tokens(text_a)
    sb = _keyword_tokens(text_b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    denom = max(len(sa), len(sb))
    return inter / denom if denom > 0 else 0.0


def purpose_alignment_score(
    *,
    purpose_text: str,
    ku_text: str,
    embedding_purpose: list[float],
    embedding_ku: list[float],
) -> float:
    """Score how well a KU aligns with a given purpose (0.0–1.0).

    Weighted average: 0.6 * cosine_similarity + 0.4 * keyword_overlap.
    Raises ValueError if purpose_text is empty.
    """
    if not purpose_text.strip():
        raise ValueError("purpose_text must not be empty")

    cos = _cosine_sim(embedding_purpose, embedding_ku)
    kw = _keyword_overlap(purpose_text, ku_text)
    return 0.6 * cos + 0.4 * kw

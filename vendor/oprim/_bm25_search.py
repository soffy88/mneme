"""oprim.bm25_search — single BM25 keyword retrieval call.

3O layer: oprim (single atomic call, pure BM25 algorithm, no LLM).
Handles precise identifier matching (ADR-038) that pure vectors miss.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict


def _tokenize(text: str) -> list[str]:
    """Tokenize text: lowercase, keep alphanumeric + hyphens and CJK chars."""
    return re.findall(r"[A-Za-z0-9\-]+|[一-鿿]+", text.lower())


def bm25_search(
    *,
    query: str,
    docs: dict[str, str],
    k1: float = 1.5,
    b: float = 0.75,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """BM25 keyword retrieval. docs: {doc_id: text}. Returns [(doc_id, score)] descending.

    Precise identifier matching (e.g. ADR-038) that pure vector search misses.
    Empty query or empty docs returns [].
    """
    if not docs:
        return []
    q_terms = _tokenize(query)
    if not q_terms:
        return []

    doc_tokens: dict[str, list[str]] = {d: _tokenize(t) for d, t in docs.items()}
    N = len(docs)
    avgdl = sum(len(t) for t in doc_tokens.values()) / N

    # document frequency per term
    df: dict[str, int] = defaultdict(int)
    for toks in doc_tokens.values():
        for term in set(toks):
            df[term] += 1

    scores: dict[str, float] = {}
    for d, toks in doc_tokens.items():
        dl = len(toks)
        tf: dict[str, int] = defaultdict(int)
        for term in toks:
            tf[term] += 1
        s = 0.0
        for term in q_terms:
            if term not in df:
                continue
            idf = math.log(1 + (N - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scores[d] = s

    return sorted(scores.items(), key=lambda x: -x[1])[:top_k]

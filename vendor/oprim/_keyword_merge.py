"""P-AII-2: keyword_merge — pure-string keyword extraction and text grouping.

Zero external dependencies: uses re + built-in stop-word list only.
No embedding, no LLM.
"""

from __future__ import annotations

import re
from collections import defaultdict


_DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    # Chinese single-character function words
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "看", "好",
    "他", "她", "它", "们", "与", "及", "对", "为", "从", "以", "但", "而",
    "则", "或", "并", "且", "中", "被", "把", "将", "如", "于", "后", "前",
    "时", "下", "所", "等", "用", "来", "可", "能", "已", "其", "之", "此",
    # Chinese multi-character function words
    "这个", "那个", "一个", "没有", "自己",
    # English
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "this", "that", "these", "those",
    "it", "its", "i", "you", "he", "she", "we", "they", "not", "no", "as",
    "if", "so", "than", "then", "when", "where", "which", "who", "what",
    "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "into", "about", "up", "out", "can", "get", "just",
    "also", "been", "use", "used",
})

# Minimum token length to be considered a keyword
_MIN_TOKEN_LEN = 2


def _extract_keywords(text: str, stopwords: set[str]) -> set[str]:
    """Extract non-stopword tokens: ASCII whole-words + Chinese character bigrams."""
    result: set[str] = set()

    # ASCII words (case-normalised)
    for tok in re.findall(r"[a-zA-Z0-9]+", text):
        lower = tok.lower()
        if lower not in stopwords and len(lower) >= _MIN_TOKEN_LEN:
            result.add(lower)

    # Chinese: slide a bigram window over each contiguous run of CJK characters.
    # Bigrams act as pseudo-words and enable overlap detection without a tokenizer.
    for run in re.findall(r"[一-鿿]+", text):
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in stopwords:
                result.add(bigram)

    return result


def keyword_merge(
    texts: list[str],
    *,
    stopwords: set[str] | None = None,
) -> dict[str, list[str]]:
    """Group texts by keyword overlap; return {representative_text: [member_texts]}.

    Texts that share at least one non-stopword keyword are merged into the same group.
    The representative is the first element (by original order) in each connected component.

    Args:
        texts: Input strings to group. Empty list returns {}.
        stopwords: Override the built-in Chinese+English stop-word set.

    Returns:
        Mapping of representative → list of all members (including the representative).
    """
    if not texts:
        return {}
    if len(texts) == 1:
        return {texts[0]: [texts[0]]}

    sw: set[str] = stopwords if stopwords is not None else _DEFAULT_STOPWORDS  # type: ignore[assignment]

    keywords: list[set[str]] = [_extract_keywords(t, sw) for t in texts]

    # Union-Find with path compression
    parent = list(range(len(texts)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Always root at the lower index so the representative is stable
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if keywords[i] and keywords[j] and keywords[i] & keywords[j]:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(texts)):
        groups[find(idx)].append(idx)

    return {
        texts[root]: [texts[m] for m in sorted(members)]
        for root, members in sorted(groups.items())
    }

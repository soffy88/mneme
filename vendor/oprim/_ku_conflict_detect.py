"""P-G1: ku_conflict_detect — two-step conflict candidate detection.

Step 1: cosine similarity > threshold (semantic relevance gate).
Step 2: polarity keyword pair detection (opposing/neutral/insufficient).

Pure computation, no LLM. Deterministic.
"""
from __future__ import annotations

from oprim._aii_graph_types import ConflictSignal

_POLARITY_PAIRS: list[tuple[str, str]] = [
    # Chinese
    ("增加", "减少"), ("增长", "下降"), ("上升", "下降"),
    ("扩大", "缩小"), ("支持", "反对"), ("证明", "反驳"),
    ("肯定", "否定"), ("有效", "无效"), ("成功", "失败"),
    ("正相关", "负相关"), ("促进", "抑制"), ("同意", "拒绝"),
    ("正确", "错误"), ("优势", "劣势"),
    # English
    ("increase", "decrease"), ("positive", "negative"),
    ("support", "oppose"), ("confirm", "refute"),
    ("expand", "shrink"), ("promote", "inhibit"),
    ("agree", "disagree"), ("accept", "reject"),
    ("valid", "invalid"), ("success", "failure"),
]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"embedding dimensions differ: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _check_polarity(text_a: str, text_b: str) -> tuple[str, str]:
    """Return (polarity_signal, evidence) for the two texts."""
    ta, tb = text_a.lower(), text_b.lower()
    if not ta.strip() or not tb.strip():
        return "insufficient", ""
    for w1, w2 in _POLARITY_PAIRS:
        w1l, w2l = w1.lower(), w2.lower()
        if (w1l in ta and w2l in tb) or (w2l in ta and w1l in tb):
            return "opposing", f"{w1!r}↔{w2!r}"
    return "neutral", ""


def ku_conflict_detect(
    *,
    ku_text_a: str,
    ku_text_b: str,
    embedding_a: list[float],
    embedding_b: list[float],
    similarity_threshold: float = 0.6,
) -> ConflictSignal:
    """Detect whether two KUs are conflict candidates.

    Two-step: (1) cosine similarity gate, (2) polarity keyword detection.
    Embeddings must have the same dimension; raises ValueError otherwise.
    """
    if len(embedding_a) != len(embedding_b):
        raise ValueError(
            f"embedding dimensions differ: {len(embedding_a)} vs {len(embedding_b)}"
        )

    sim = _cosine_sim(embedding_a, embedding_b)

    if sim <= similarity_threshold:
        return ConflictSignal(
            is_conflict_candidate=False,
            similarity=sim,
            polarity_signal="neutral",
            evidence="",
        )

    polarity, evidence = _check_polarity(ku_text_a, ku_text_b)

    return ConflictSignal(
        is_conflict_candidate=(polarity == "opposing"),
        similarity=sim,
        polarity_signal=polarity,
        evidence=evidence,
    )

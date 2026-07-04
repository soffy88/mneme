"""oprim._readability_score — Flesch-Kincaid Grade Level（确定性，纯计算，非 LLM）

U.19 英语习得型范式：分级泛读文章难度分档，公式化、无外部依赖，跟词频统计
（_word_frequency_stats.py）一样是对已授权文本的确定性计算。
"""

from __future__ import annotations

import re

_SENTENCE_END_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"[a-zA-Z]+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+", re.IGNORECASE)


def _count_syllables(word: str) -> int:
    """启发式音节计数：元音组数，词尾静音 e 扣一个，至少 1。"""
    groups = _VOWEL_GROUP_RE.findall(word)
    n = len(groups)
    if word.lower().endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid Grade Level = 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59。

    文本过短（<1 句或 <1 词）返回 0.0，不外推。
    """
    words = _WORD_RE.findall(text)
    sentences = [s for s in _SENTENCE_END_RE.split(text) if s.strip()]
    n_words = len(words)
    n_sentences = max(1, len(sentences))
    if n_words == 0:
        return 0.0

    n_syllables = sum(_count_syllables(w) for w in words)
    score = 0.39 * (n_words / n_sentences) + 11.8 * (n_syllables / n_words) - 15.59
    return round(max(0.0, score), 2)


def assign_difficulty_bands(scored_items: list[dict], n_bands: int = 5) -> list[dict]:
    """按 readability_score 分位数切 1..n_bands 难度分档（1=最易），复用与词频
    分档相同的分位数切法，保证两套 1-5 尺度可比（i+1 对齐的前提）。

    输入 scored_items: [{"readability_score": float, ...}, ...]。
    """
    import math

    n = len(scored_items)
    if n == 0:
        return []
    ordered = sorted(range(n), key=lambda i: scored_items[i]["readability_score"])
    rank_of = {idx: rank + 1 for rank, idx in enumerate(ordered)}
    out = []
    for i, item in enumerate(scored_items):
        rank = rank_of[i]
        band = min(n_bands, max(1, math.ceil(rank * n_bands / n)))
        out.append({**item, "difficulty_band": band})
    return out


__all__ = ["flesch_kincaid_grade", "assign_difficulty_bands"]

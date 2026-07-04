"""oprim._word_frequency_stats — 语料库词频统计（确定性，纯计算，非 LLM）

U.19 英语习得型范式：词汇难度分档不依赖许可不明的第三方词表，改为直接对
自建语料库（Simple English Wikipedia，CC BY-SA 4.0）做词频统计——分档是
对已授权文本的统计事实，不是对外部专有词表的复制。
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")


def tokenize(text: str) -> list[str]:
    """小写化 + 只保留字母/内部撇号（it's）token，丢弃标点/数字。"""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def compute_word_frequency(texts: list[str]) -> list[dict]:
    """跨语料库统计词频，按频率降序排名（rank 从 1 开始）。

    Returns
    -------
    list[dict]
        每项 {"word": str, "count": int, "rank": int}，按 count 降序、
        同频按字母序稳定排序。
    """
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(tokenize(text))

    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"word": word, "count": count, "rank": i + 1}
        for i, (word, count) in enumerate(ranked)
    ]


def assign_frequency_bands(ranked_words: list[dict], n_bands: int = 5) -> list[dict]:
    """按 rank 等分位数切分 1..n_bands 频率分档（1=最高频）。

    输入必须是 compute_word_frequency 的输出（已按 rank 排序）。
    """
    n = len(ranked_words)
    if n == 0:
        return []
    out = []
    for item in ranked_words:
        band = min(n_bands, max(1, math.ceil(item["rank"] * n_bands / n)))
        out.append({**item, "frequency_band": band})
    return out


_RAW_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def find_lowercase_attested_words(texts: list[str]) -> set[str]:
    """返回语料库中以纯小写形式出现过至少一次的词（原始大小写，未 tokenize 前）。

    专有名词（人名/地名等）在语料库里几乎只以大写开头形式出现——用这个集合
    过滤词频候选，排除专有名词混入词汇表（Wikipedia 人物/地名条目占比高，
    直接按词频取 top-N 会被专有名词淹没）。
    """
    attested: set[str] = set()
    for text in texts:
        for m in _RAW_WORD_RE.finditer(text):
            w = m.group(0)
            if w.islower():
                attested.add(w)
    return attested


__all__ = [
    "tokenize",
    "compute_word_frequency",
    "assign_frequency_bands",
    "find_lowercase_attested_words",
]

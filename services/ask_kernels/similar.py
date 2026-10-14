"""没有精确内核时：从已解题库里找最相似的 3 道题（带解答），不调用 LLM。

题库 = services/ask_kernels/data/solved_bank.json（scripts/build_ask_bank.py 生成：评测语料里
被内核解出的题 + 种子题库里带答案的题）。相似度 = 字符 2-gram 的余弦相似度 + 题型关键词加权。
教材原文段落另由 photo_ask_service 通过 knowledge_hub_search 词面/向量检索补充（可选，带超时）。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.ask_kernels.core import basic_normalize

_BANK = Path(__file__).with_name("data") / "solved_bank.json"
_TYPE_WORDS = re.compile(
    r"方程组|方程|不等式|因式分解|化简|函数|抛物线|三角形|勾股|圆|扇形|多边形|相似|概率|平均数|方差|中位数|"
    r"相遇|追及|工程|利润|折|浓度|年龄|鸡兔|速度|密度|压强|浮力|杠杆|功率|热量|电阻|电流|电压|质量分数|相对分子质量|溶液"
)


def _grams(text: str) -> Counter:
    t = re.sub(r"\s+", "", basic_normalize(text))
    t = re.sub(r"\d+(?:\.\d+)?", "#", t)  # 数字不同不影响“同类题”
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@lru_cache(maxsize=1)
def _bank() -> list[dict[str, Any]]:
    try:
        items = json.loads(_BANK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("text") or not it.get("answer"):
            continue
        it = dict(it)
        it["_g"] = _grams(it["text"])
        it["_types"] = set(_TYPE_WORDS.findall(it["text"]))
        out.append(it)
    return out


def similar_questions(text: str, subject: str | None = None, k: int = 3, min_score: float = 0.12) -> list[dict[str, Any]]:
    """返回 [{text, answer, steps, hint, kernel, subject, score, source}]，最多 k 道。"""
    q = _grams(text)
    qt = set(_TYPE_WORDS.findall(basic_normalize(text)))
    scored = []
    for it in _bank():
        s = _cos(q, it["_g"])
        if qt and it["_types"] & qt:
            s += 0.15
        if subject and it.get("subject") and it["subject"] != subject:
            s -= 0.2
        if s >= min_score:
            scored.append((s, it))
    scored.sort(key=lambda t: -t[0])
    out = []
    seen = set()
    for s, it in scored:
        key = re.sub(r"\d+", "#", it["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": it["text"],
            "answer": it["answer"],
            "steps": list(it.get("steps") or [])[:8],
            "hint": it.get("hint"),
            "kernel": it.get("kernel"),
            "subject": it.get("subject"),
            "score": round(s, 3),
            "source": it.get("source", "bank"),
        })
        if len(out) >= k:
            break
    return out


__all__ = ["similar_questions"]

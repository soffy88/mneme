"""确定性（无 LLM）答题 provider：英语查词/语法、语文拼音/古诗词/成语。

给求解路由（services.ask_kernels* / photo_ask_service.solve_question）用的稳定钩子：

    from services.ask_providers import solve_with_providers
    out = solve_with_providers(text, subject)   # 同步、毫秒级、永不抛；不适用返回 None

单个 provider 也可直接调用（签名固定，router 可自行编排顺序）：

    from services.ask_providers.english import english_lookup_solve   # (text) -> dict | None
    from services.ask_providers.chinese import chinese_lookup_solve   # (text) -> dict | None

返回 dict 与精确内核 KernelSolution.to_dict() 同形：
    {"kernel": "english.word" | "english.inflection" | "english.grammar" | "english.choice"
               | "chinese.pinyin" | "chinese.poem" | "chinese.idiom",
     "answer": str, "steps": [str], "hint": str, "explanation": str,
     "card": {...}  # 可选：前端卡片（english_word / poem / pinyin / idiom），见 README.md}

调用方应在精确数学/化学内核之后、LLM 之前调用（数学题不会被这里误判：两个 provider 都有题型闸门）。
详见 services/ask_providers/README.md。
"""

from __future__ import annotations

import re
from typing import Optional

from services.ask_providers.chinese import chinese_lookup_solve
from services.ask_providers.english import english_lookup_solve

PROVIDERS = {"english": english_lookup_solve, "chinese": chinese_lookup_solve}


def provider_order(text: str, subject: Optional[str]) -> list[str]:
    if subject == "english":
        return ["english", "chinese"]
    if subject == "chinese":
        return ["chinese", "english"]
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    han = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    return ["english", "chinese"] if latin > han else ["chinese", "english"]


def solve_with_providers(text: str, subject: Optional[str] = None) -> Optional[dict]:
    """按学科/文字比例依次尝试各 provider，第一个命中即返回（附 provider 名）。永不抛。"""
    for name in provider_order(text, subject):
        try:
            out = PROVIDERS[name](text)
        except Exception:  # noqa: BLE001
            out = None
        if out:
            out.setdefault("subject", name)
            return out
    return None


__all__ = ["PROVIDERS", "chinese_lookup_solve", "english_lookup_solve", "provider_order", "solve_with_providers"]

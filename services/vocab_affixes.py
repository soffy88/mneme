"""services/vocab_affixes.py — 词根词缀的展示格式与校验。

用户需求：单词卡的解释面按 `前缀·词根·后缀` 分段显示，用 `·` 隔开。

**分隔符约定**（渲染层依赖，改这里等于改 UI）：
    pre · dict            前缀 + 词根
    dict                  只有词根
    dict · able           词根 + 后缀
    dis · cover           前后缀都有
    分段之间用一个半角·，两侧各留一个空格；缺哪段就省略哪段，不留空占位。

链上任何一段缺失都不是错误（很多词只有词根），空链返回 ""。
"""

from __future__ import annotations

# 展示分隔符。半角中点，两侧各一个空格。
AFFIX_SEPARATOR = " · "

# 常见词缀形态校验用的字符集：只允许字母、数字、连字符、撇号、点。
# 词根可能写成拉丁原形（capere）或带屈折（-ing），都放行。
_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'. ")


def format_affix_chain(
    prefix: str | None,
    root: str | None,
    suffix: str | None,
) -> str:
    """把三段拼成展示串：`pre · dict · able`。缺段省略，全空返回 ""。"""
    parts = [p.strip() for p in (prefix, root, suffix) if p and p.strip()]
    return AFFIX_SEPARATOR.join(parts)


def validate_segment(seg: str | None, *, max_len: int) -> str | None:
    """校验单个词根/词缀段。合法返回清理后的值，非法返回 None。

    非法就返回 None 而不是尽力修补 —— 这些值是要给学生背的，宁缺勿错。
    """
    if seg is None:
        return None
    s = seg.strip()
    if not s or len(s) > max_len:
        return None
    if not _ALLOWED.issuperset(s):
        return None
    if not any(c.isalpha() for c in s):
        return None
    return s


def affix_payload(
    *,
    prefix: str | None,
    root: str | None,
    suffix: str | None,
    meaning_cn: str | None = None,
    origin: str | None = None,
    source: str | None = None,
    confidence: float | None = None,
) -> dict:
    """给 API / 前端用的载荷。chain 是前端直接渲染的展示串。"""
    return {
        "prefix": prefix or None,
        "root": root,
        "suffix": suffix or None,
        "chain": format_affix_chain(prefix, root, suffix),
        "meaning_cn": meaning_cn,
        "origin": origin,
        "source": source,
        "confidence": confidence,
    }


__all__ = [
    "AFFIX_SEPARATOR",
    "affix_payload",
    "format_affix_chain",
    "validate_segment",
]
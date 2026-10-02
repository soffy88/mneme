"""services/vocab_affixes.py — 词根词缀的展示格式、校验与**可信档位**。

用户需求：单词卡的解释面按 `前缀·词根·后缀` 分段显示，用 `·` 隔开。

**分隔符约定**（渲染层依赖，改这里等于改 UI）：
    pre · dict            前缀 + 词根
    dict                  只有词根
    dict · able           词根 + 后缀
    dis · cover           前后缀都有
    分段之间用一个半角·，两侧各留一个空格；缺哪段就省略哪段，不留空占位。

链上任何一段缺失都不是错误（很多词只有词根），空链返回 ""。

**可信档位约定**（渲染层同样依赖）：
    reference_confirmed    与教学参考词根表一致 —— 可当作词源讲
    mnemonic_association   人为联想，无参考佐证 —— 只能当记忆提示讲
    disputed               与参考表冲突 —— 待人工判读，不应直接展示
库内 379 条的**权威来源只是散文里「词根/前缀/后缀」的标注**，不是历史语言学
（散文自身就常把词干/后缀写成「词根」：`careless→less`、`chinese→ese`）。按
「单词深度记忆引擎 V2」自己的标准，这些属于记忆联想，**不得与词源同屏同权**。
"""

from __future__ import annotations

# 展示分隔符。半角中点，两侧各一个空格。
AFFIX_SEPARATOR = " · "

# 可信档位。与 alembic a3b4c5d6e7f8 的 etymology_status 取值一致。
STATUS_REFERENCE_CONFIRMED = "reference_confirmed"
STATUS_MNEMONIC_ASSOCIATION = "mnemonic_association"
STATUS_DISPUTED = "disputed"

# 只有 reference_confirmed 可以按「词源」讲。其余两档都不能。
SOURCE_BEARING_STATUSES = frozenset({STATUS_REFERENCE_CONFIRMED})

# 展示层建议的标注后缀（供前端加提示，不是强制）。
# disputed 默认**不展示** —— 与参考表冲突时任何一方都可能错。
STATUS_LABEL = {
    STATUS_REFERENCE_CONFIRMED: "",
    STATUS_MNEMONIC_ASSOCIATION: "（记忆联想）",
    STATUS_DISPUTED: "（存疑，待校对）",
}

# 常见词缀形态校验用的字符集：只允许字母、数字、连字符、撇号、点。
# 词根可能写成拉丁原形（capere）或带屈折（-ing），都放行。
_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'. ")


def is_source_bearing(status: str | None) -> bool:
    """该分解能否按「词源事实」呈现。只有参考表佐证过才算。"""
    return (status or "") in SOURCE_BEARING_STATUSES


def should_display(status: str | None) -> bool:
    """默认展示策略：disputed（与参考表冲突）不展示，待人工判读。"""
    return (status or STATUS_MNEMONIC_ASSOCIATION) != STATUS_DISPUTED


def annotate_chain(chain: str, status: str | None) -> str:
    """给展示串加档位标注。`reference_confirmed` 不加任何后缀。"""
    label = STATUS_LABEL.get(status or STATUS_MNEMONIC_ASSOCIATION, "")
    if not chain or not label:
        return chain
    return f"{chain} {label}"


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
    etymology_status: str | None = None,
) -> dict:
    """给 API / 前端用的载荷。

    chain 是前端直接渲染的展示串；`display_chain` 带档位标注；
    `is_source_bearing` 告诉前端能否把这段当词源讲（决定字体/是否加提示）。
    """
    status = etymology_status or STATUS_MNEMONIC_ASSOCIATION
    chain = format_affix_chain(prefix, root, suffix)
    return {
        "prefix": prefix or None,
        "root": root,
        "suffix": suffix or None,
        "chain": chain,
        "display_chain": annotate_chain(chain, status),
        "etymology_status": status,
        "is_source_bearing": is_source_bearing(status),
        "should_display": should_display(status),
        "meaning_cn": meaning_cn,
        "origin": origin,
        "source": source,
        "confidence": confidence,
    }


__all__ = [
    "AFFIX_SEPARATOR",
    "STATUS_DISPUTED",
    "STATUS_LABEL",
    "STATUS_MNEMONIC_ASSOCIATION",
    "STATUS_REFERENCE_CONFIRMED",
    "annotate_chain",
    "affix_payload",
    "format_affix_chain",
    "is_source_bearing",
    "should_display",
    "validate_segment",
]
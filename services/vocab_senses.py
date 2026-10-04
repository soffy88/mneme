"""services/vocab_senses.py — 从 `canonical_meaning` 还原多义项，并选出**主义项**

## 为什么需要它（20 词人工审查的实测发现）

`vocabulary_items.canonical_meaning` 存的是教材词表里的**完整多义项**
（每行一个义项，带词性前缀），但 `meaning_cn` 往往**只截了第一个义项**：

| 词 | `meaning_cn`（引擎实际吃到的） | `canonical_meaning` 完整义项 | 后果 |
|---|---|---|---|
| `blind` | 掩饰，借口；百叶窗 | + **adj. 盲目的；瞎的** / vt. 使失明 | 记忆卡锚在**百叶窗**上 |
| `wet` | 雨天；湿气 | + **adj. 潮湿的；有雨的** | 锚在「雨天」而非「潮湿」 |
| `fine` | 罚款 | + **adj. 好的；优良的** | 锚在「罚款」而非「好的」 |

学生于是记住**冷门义项**。实测规模：核心单词里 **1,288** 词是多义项，
其中 **1,190** 词的 `meaning_cn` 长度不足 `canonical_meaning` 的一半。

## 关键设计：**派生，不落库**

本模块**不建表、不写库**。完整义项本来就在 `canonical_meaning` 里（教材原文，
可追溯），缺的只是「读的时候怎么选主义项」。所以这里做成**读时纯函数**：

- 不产生第二份数据源 → 不会有「义项表 vs canonical_meaning」互相漂移；
- 不需要迁移，不动历史数据；
- 教材原文一改，主义项自动跟着变。

## 选义项规则（确定性，无 LLM）

用 `vocabulary_items.pos` —— 它来自**人工编排的默写表**
（`scripts/import_pos_from_dictation.py`），是**策展值**而非推断值（与
`meaning_cn` 不同，后者是派生值）。规则：

1. `pos` 有值 → 选**词性相符**的那个义项（上表三例全部命中）；
2. `pos` 为空 → 取**第一个**非占位义项（`title` 走这条，首义项「头衔/标题」正确）；
3. 词性都对不上 → 取第一个非占位义项，并在 `reason` 里说明是兜底。

⚠️ **不覆盖 `meaning_cn`**。它是「教材词表原文」这一可追溯性的载体；改它等于
悄悄改掉学生看到的权威释义。义项选择只影响**记忆引擎喂给 LLM 的那一份**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.vocab_meaning import is_phonetic_transcription

# 义项行：行首的词性标签，如 `n.` / `vt.` / `adj.` / `link v.` / `interj.`
_POS_LINE_RE = re.compile(r"^\s*((?:[A-Za-z]+\.?\s*){1,3}?)\s+(\S.*)$", re.DOTALL)
# 义项标签：`[法]` `[计]` `[气象][物]` `（美）` —— 是**领域/义项标签**，不是音标
_SENSE_TAG_RE = re.compile(r"^[\[（(][^\[（(）)\]]{1,8}[\]）)]\s*")

PLACEHOLDERS = frozenset({"", "无", "-", "—", "/", "n/a", "N/A", "null", "NULL"})

# 词性归一。教材缩写（a/ad）与规范缩写（adj/adv）都要认。
_POS_CANON = {
    "n": "noun", "noun": "noun", "n.": "noun",
    "v": "verb", "vt": "verb", "vi": "verb", "verb": "verb",
    "link v": "verb", "aux": "verb", "mod": "verb",
    "adj": "adj", "a": "adj", "adjective": "adj",
    "adv": "adv", "ad": "adv", "adverb": "adv",
    "prep": "prep", "conj": "conj", "pron": "pron", "det": "det",
    "num": "num", "art": "art", "int": "interj", "interj": "interj",
    "abbr": "noun", "pl": "noun",
}


@dataclass(frozen=True)
class Sense:
    """一个义项。``pos`` 是归一后的词性（noun/verb/adj…），``raw_pos`` 是原文标签。"""

    order: int
    pos: str | None
    raw_pos: str | None
    text: str

    def to_payload(self) -> dict[str, object]:
        return {"order": self.order, "pos": self.pos, "raw_pos": self.raw_pos, "text": self.text}


def canon_pos(raw: str | None) -> str | None:
    """把词性标签归一。`link v.` / `v & n` 这类也认（取第一个）。"""
    if not raw:
        return None
    s = raw.strip().lower().replace(".", " ").replace("&", " ").split()
    if not s:
        return None
    # `link v` → 先试两词组合，再退化到单词
    for size in (2, 1):
        if len(s) >= size:
            key = " ".join(s[:size])
            key = key.replace(" .", "")
            if key in _POS_CANON:
                return _POS_CANON[key]
    return _POS_CANON.get(s[0])


def parse_senses(canonical_meaning: str | None) -> list[Sense]:
    """把 `canonical_meaning` 的每一行还原成一个义项。纯函数。

    识别不了行首词性标签时，整行当作**无词性**义项（不是丢弃）—— 教材表里
    确实有无标签的义项行。
    """
    raw = (canonical_meaning or "").strip()
    if not raw:
        return []
    # 音标不是义项（CME-P1.5：canonical_meaning 里混着 9,844 条真音标）。
    # 判定复用 services.vocab_meaning 的**唯一源**，不自己再写一遍。
    if is_phonetic_transcription(raw):
        return []
    senses: list[Sense] = []
    order = 0
    for line in raw.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line in PLACEHOLDERS:
            continue
        raw_pos = None
        body = line
        m = _POS_LINE_RE.match(line)
        if m and len(m.group(1)) <= 14 and "." in m.group(1) + ".":
            raw_pos = m.group(1).strip()
            body = m.group(2).strip()
        # 义项标签可能连续多个（`[气象][物] 潮湿的`），要**全部**剥掉
        prev = None
        while prev != body:
            prev = body
            body = _SENSE_TAG_RE.sub("", body).strip()
        if not body or body in PLACEHOLDERS:
            continue
        senses.append(
            Sense(order=order, pos=canon_pos(raw_pos), raw_pos=raw_pos, text=body)
        )
        order += 1
    return senses


def select_primary_sense(
    canonical_meaning: str | None, pos_column: str | None
) -> tuple[Sense | None, str]:
    """选出主义项。返回 ``(义项, 选中理由)``；找不到返回 ``(None, 原因)``。

    ``pos_column`` 是 ``vocabulary_items.pos``（来自默写表的策展值）。
    """
    senses = parse_senses(canonical_meaning)
    if not senses:
        return None, "canonical_meaning 里没有可用义项"

    want = canon_pos(pos_column)
    if want:
        for s in senses:
            if s.pos == want:
                return s, f"pos 列={pos_column!r} → 命中第 {s.order} 个义项（{s.raw_pos}）"
        return (
            senses[0],
            f"pos 列={pos_column!r} 与所有义项词性都不符，兜底取第 0 个",
        )
    return senses[0], "pos 列为空，取第一个非占位义项"


__all__ = [
    "PLACEHOLDERS",
    "Sense",
    "canon_pos",
    "parse_senses",
    "select_primary_sense",
]

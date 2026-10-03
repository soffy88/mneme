"""services/vocab_context.py — 词汇记忆引擎的 Context Retriever（教材优先）

MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §1.1 的实现：把 VocabularyItem 连到**真实语境句**。

按 Context Priority 逐层取，取到即止：

======  ====================  ==========================================
tier    名称                 现状（2026-10-03 生产实测）
======  ====================  ==========================================
1       CURRENT_LESSON       **BLOCKED**：无源
2       CURRENT_BOOK         **BLOCKED**：无源
3       NCE                  ✅ 13,017 句
4       PUBLIC_CORPUS        **BLOCKED**：无库
5       NONE                 ✅ 显式降级
======  ====================  ==========================================

tier 1/2 不可用的原因不是「还没做」，而是**数据链没打通**：559 个 lesson **全是 NCE**，
且 ``lessons.book_id ∩ books`` 实测为 **0**，所以「当前教材那句话」在库里不存在。
硬编码成 tier 5 会让调用方以为「这个学生学的教材里没有这个词」——那是**假的**，
会让教材优先这条产品承诺静默消失。故这里**显式**返回不可用 + 原因。

纯确定性（无 LLM）、只读、无副作用，故可完整单测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.vocab_meaning import classify_meaning_source

TIER_CURRENT_LESSON = 1
TIER_CURRENT_BOOK = 2
TIER_NCE = 3
TIER_PUBLIC_CORPUS = 4
TIER_NONE = 5

_TIER_NAMES = {
    TIER_CURRENT_LESSON: "CURRENT_LESSON",
    TIER_CURRENT_BOOK: "CURRENT_BOOK",
    TIER_NCE: "NCE",
    TIER_PUBLIC_CORPUS: "PUBLIC_CORPUS",
    TIER_NONE: "NONE",
}

# tier 1/2/4 今天没有数据源。写下原因是为了让调用方能区分
# 「这个学生学的教材里没有这个词」和「我们还没接入教材句」——后者不是学生的错。
TIER_UNAVAILABLE_REASON: dict[int, str] = {
    TIER_CURRENT_LESSON: (
        "lessons 全部为 NCE（559/559），无「当前课」概念；"
        "lessons.book_id 与 books 零交集，当前教材课句子在库中不存在"
    ),
    TIER_CURRENT_BOOK: (
        "lessons.book_id 与 books 零交集，教材课本维度未接入课程链，"
        "无法定位「当前教材的哪一句」"
    ),
    TIER_PUBLIC_CORPUS: "无语料库（reading_passages 仅 41 行，不构成语料）",
}

# 句长最佳区间，与 scripts/extract_vocab_examples.py 同源：太短没有记忆锚点，
# 太长学生读不完也不构成「一个用法」。
_SENTENCE_MIN_LEN = 20
_SENTENCE_MAX_LEN = 160


@dataclass
class ContextSentence:
    text: str
    chinese_text: str | None
    source: str
    lesson: str | None
    sentence_id: str


@dataclass
class ContextBundle:
    """一个词的语境包。``tier`` 是**实际取到的层**，不是最高可用层。"""

    tier: int
    sentences: list[ContextSentence] = field(default_factory=list)
    unavailable_tiers: list[int] = field(default_factory=list)

    @property
    def tier_name(self) -> str:
        return _TIER_NAMES[self.tier]

    @property
    def has_context(self) -> bool:
        return self.tier < TIER_NONE and bool(self.sentences)

    @property
    def best(self) -> ContextSentence | None:
        return self.sentences[0] if self.sentences else None

    def to_payload(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_name": self.tier_name,
            "textbook_tier_available": TIER_CURRENT_LESSON not in self.unavailable_tiers,
            "unavailable_tiers": [
                {"tier": t, "tier_name": _TIER_NAMES[t], "reason": TIER_UNAVAILABLE_REASON[t]}
                for t in self.unavailable_tiers
            ],
            "sentences": [
                {
                    "text": s.text,
                    "chinese_text": s.chinese_text,
                    "source": s.source,
                    "lesson": s.lesson,
                    "sentence_id": s.sentence_id,
                }
                for s in self.sentences
            ],
            "degradation_reason": None
            if self.has_context
            else "该词在已接入的语料中无真实语境句（无语料源，见 unavailable_tiers）",
        }


# tier 1/2 今天永远不可用。写成数据而非 if/else，是为了让「接入教材源」这件事
# 只需要改这一处 + 给两个 tier 加查询，而不是散落在各处 if 里。
_ALL_UNAVAILABLE = [TIER_CURRENT_LESSON, TIER_CURRENT_BOOK, TIER_PUBLIC_CORPUS]


async def retrieve_context(
    db: Any,
    vocabulary_item_id: str,
    *,
    limit: int = 3,
) -> ContextBundle:
    """取一个词的语境包。逐层降级，取到即止；全程只读、无 LLM。"""
    if limit < 1:
        raise ValueError("limit 必须 >= 1")

    sentences = await _nce_sentences(db, vocabulary_item_id, limit=limit)
    if sentences:
        return ContextBundle(
            tier=TIER_NCE, sentences=sentences, unavailable_tiers=list(_ALL_UNAVAILABLE)
        )
    return ContextBundle(tier=TIER_NONE, sentences=[], unavailable_tiers=list(_ALL_UNAVAILABLE))


async def _nce_sentences(db: Any, vocabulary_item_id: str, *, limit: int) -> list[ContextSentence]:
    """NCE 层：从 timed_sentences 取真实句。

    句长偏好区间固定为 [_SENTENCE_MIN_LEN, _SENTENCE_MAX_LEN]，超界的仍然取用
    （有胜于无），只是排在后面——「宁可长句也不要没语境」。
    """
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                """
        SELECT ts.id, ts.english_text, ts.chinese_text, l.title
        FROM sentence_vocabulary_occurrences o
        JOIN timed_sentences ts ON ts.id = o.sentence_id
        JOIN lessons l ON l.id = ts.lesson_id
        WHERE o.vocabulary_item_id = :vid
          AND ts.english_text IS NOT NULL
          AND btrim(ts.english_text) <> ''
        ORDER BY
          CASE WHEN length(ts.english_text) BETWEEN :lo AND :hi THEN 0
               WHEN length(ts.english_text) BETWEEN :lo2 AND :lo THEN 1
               ELSE 2 END,
          o.occurrence_index,
          ts.id
        LIMIT :limit
        """
            ),
            {
                "vid": vocabulary_item_id,
                "lo": _SENTENCE_MIN_LEN,
                "hi": _SENTENCE_MAX_LEN,
                "lo2": 10,
                "limit": limit,
            },
        )
    ).all()
    return [
        ContextSentence(
            text=r.english_text.strip(),
            chinese_text=(r.chinese_text or None),
            source="NCE",
            lesson=r.title or None,
            sentence_id=str(r.id),
        )
        for r in rows
    ]


async def load_memory_input(
    db: Any,
    vocabulary_item_id: str,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """组装 oprim._vocab_memory_generate 的输入契约（spec §1.1）。

    只读既有事实表拼装，不做任何生成。
    """
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                """
        SELECT v.id, v.word, v.pos, v.meaning_cn, v.phonetic_arpabet,
               v.example_sentence, v.canonical_meaning
        FROM vocabulary_items v
        WHERE v.id = :vid
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).first()
    if row is None:
        raise KeyError(f"vocabulary_item 不存在: {vocabulary_item_id}")

    # 释义必须先过判定闸：教材词表把音标和释义写进同一列（实测全表 9,844 条真音标、
    # 11 条带义项标签的释义被旧规则误拒），LLM 绝不能拿到读音当中文意思。
    meaning = classify_meaning_source(
        meaning_cn=row.meaning_cn, canonical_meaning=row.canonical_meaning
    )

    bundle = await retrieve_context(db, vocabulary_item_id, limit=limit)
    # example_sentence 是 P0.3a 从同一批 timed_sentences 确定性抽取的，重复来源
    # 不构成新证据；但当 occurrence 关联丢失时它是唯一退路，故保留为兜底。
    sentences = list(bundle.sentences)
    if not sentences and (row.example_sentence or "").strip():
        sentences = [
            ContextSentence(
                text=row.example_sentence.strip(),
                chinese_text=None,
                source="NCE",
                lesson=None,
                sentence_id="",
            )
        ]
        bundle = ContextBundle(
            tier=TIER_NCE,
            sentences=sentences,
            unavailable_tiers=list(_ALL_UNAVAILABLE),
        )

    affix = await _affix(db, vocabulary_item_id)
    collocations = await _collocations(db, vocabulary_item_id)
    xiangxing = await _xiangxing(db, vocabulary_item_id)

    best = bundle.best
    # 只把「判定为可信释义」的那一份给 LLM。meaning.gloss 为 None 时明确传 None，
    # 让 prompt 走「未标注」分支 —— 而不是把音标塞进去让模型自己猜。
    gloss = meaning.gloss
    return {
        "vocabulary_id": row.id,
        "word": row.word,
        "pos": row.pos,
        "meaning_cn": gloss,
        "meaning": meaning.to_payload(),
        "phonetic_arpabet": row.phonetic_arpabet,
        "context": bundle.to_payload(),
        "context_flat": best.text if best else None,
        "affix": affix,
        "xiangxing": xiangxing,
        "collocations": collocations,
        "tier": await assign_tier(db, vocabulary_item_id, has_context=bundle.has_context),
        "llm_entry": {
            "word": row.word,
            "pos": row.pos,
            "meaning_cn": gloss,
            "context": best.text if best else None,
            "affix_hint": (affix or {}).get("chain"),
        },
    }


async def _affix(db: Any, vocabulary_item_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                """
        SELECT a.prefix, a.root, a.suffix, a.meaning_cn, a.origin,
               a.etymology_status
        FROM vocabulary_affixes a
        WHERE a.vocabulary_item_id = :vid
        LIMIT 1
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).first()
    if row is None:
        return None
    from services.vocab_affixes import affix_payload

    payload = affix_payload(
        prefix=row.prefix,
        root=row.root,
        suffix=row.suffix,
        meaning_cn=row.meaning_cn,
        origin=row.origin,
        source=None,
        confidence=None,
        etymology_status=row.etymology_status or "mnemonic_association",
    )
    chain = payload.get("affix_chain")
    return {
        "prefix": row.prefix,
        "root": row.root,
        "suffix": row.suffix,
        "chain": chain,
        "meaning_cn": row.meaning_cn,
        "origin": row.origin,
        "etymology_status": row.etymology_status,
        "is_source_bearing": bool(payload.get("is_source_bearing")),
        "should_display": bool(payload.get("should_display")),
    }


async def _collocations(db: Any, vocabulary_item_id: str) -> list[dict[str, str]]:
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                """
        SELECT phrase_en, phrase_cn
        FROM vocabulary_collocations
        WHERE vocabulary_item_id = :vid
        ORDER BY phrase_en
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).all()
    return [{"phrase_en": r.phrase_en, "phrase_cn": r.phrase_cn} for r in rows]


async def _xiangxing(db: Any, vocabulary_item_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                """
        SELECT ipa_ascii, meaning_cn, example_en, ownership_verified
        FROM vocabulary_xiangxing
        WHERE vocabulary_item_id = :vid
        LIMIT 1
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).first()
    if row is None:
        return None
    return {
        "ipa_ascii": row.ipa_ascii,
        "meaning_cn": row.meaning_cn,
        "example_en": row.example_en,
        "ownership_verified": bool(row.ownership_verified),
    }


async def assign_tier(db: Any, vocabulary_item_id: str, *, has_context: bool) -> str:
    """确定性分层（spec §2.4）：A 有语境+记忆锚点 / B 有语境 / C 无语境。

    **不用 ``frequency_band``** —— 实测核心范围内该列恒等于 5，无区分度。
    锚点 = ``vocabulary_affixes`` 或 ``vocabulary_xiangxing`` 有行。
    """
    if not has_context:
        return "C"
    from sqlalchemy import text

    n = (
        await db.execute(
            text(
                """
        SELECT
          EXISTS(SELECT 1 FROM vocabulary_affixes a
                 WHERE a.vocabulary_item_id = :vid) AS a,
          EXISTS(SELECT 1 FROM vocabulary_xiangxing x
                 WHERE x.vocabulary_item_id = :vid) AS x
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).first()
    return "A" if (n and (n.a or n.x)) else "B"


async def resolve_family(db: Any, words: list[str]) -> list[dict[str, Any]]:
    """把 LLM 给的 family 词解析成库内真实词。查不到的一律丢弃（spec §5 FAMILY_TRACEABLE）。

    大小写不敏感匹配；``word`` 在本表不唯一，故一条 family 词可能命中多行，
    取 id 最小的一行（确定性），并把 vocab_item_id 一并带出去。
    """
    from sqlalchemy import text

    cleaned = [w.strip().lower() for w in words if isinstance(w, str) and w.strip()]
    if not cleaned:
        return []
    rows = (
        await db.execute(
            text(
                """
        SELECT DISTINCT ON (lower(v.word)) v.id, v.word, v.meaning_cn
        FROM vocabulary_items v
        WHERE lower(v.word) = ANY(:ws)
        ORDER BY lower(v.word), v.id
        """
            ),
            {"ws": cleaned},
        )
    ).all()
    return [
        {"word": r.word, "meaning_cn": r.meaning_cn, "vocabulary_item_id": r.id} for r in rows
    ]


__all__ = [
    "TIER_CURRENT_LESSON",
    "TIER_CURRENT_BOOK",
    "TIER_NCE",
    "TIER_PUBLIC_CORPUS",
    "TIER_NONE",
    "TIER_UNAVAILABLE_REASON",
    "ContextSentence",
    "ContextBundle",
    "retrieve_context",
    "load_memory_input",
    "assign_tier",
    "resolve_family",
]
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
from services.vocab_senses import select_primary_sense

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
    learner_confused_with: str | None = None,
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
    derived = (
        await db.execute(
            text(
                """
        SELECT gloss, source_sentence_id FROM vocabulary_derived_glosses
        WHERE vocabulary_item_id = :vid LIMIT 1
        """
            ),
            {"vid": vocabulary_item_id},
        )
    ).first()
    meaning = classify_meaning_source(
        meaning_cn=row.meaning_cn,
        canonical_meaning=row.canonical_meaning,
        derived_gloss=derived.gloss if derived else None,
    )
    # 义项选择（CME-P1.6）：meaning_cn 常常只截了 canonical_meaning 的**第一个**义项，
    # 于是 `blind` 变成「百叶窗」、`wet` 变成「雨天」、`fine` 变成「罚款」—— 学生
    # 记住的是冷门义项。用 pos 列（默写表的策展值）选出主义项，**不覆盖 meaning_cn**
    # （那是「教材原文可追溯」的载体），只影响喂给 LLM 的那一份。
    primary_sense, sense_reason = select_primary_sense(row.canonical_meaning, row.pos)

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
    # 主义项优先；取不到才回落到 meaning_cn 的判定结果。
    gloss = primary_sense.text if primary_sense else meaning.gloss
    meaning_payload = meaning.to_payload()
    meaning_payload["primary_sense"] = primary_sense.to_payload() if primary_sense else None
    meaning_payload["primary_sense_reason"] = sense_reason
    meaning_payload["gloss_source"] = (
        "canonical_meaning(pos-selected sense)"
        if primary_sense
        else meaning.source_column
    )
    return {
        "vocabulary_id": row.id,
        "word": row.word,
        "pos": row.pos,
        "meaning_cn": gloss,
        "meaning": meaning_payload,
        "phonetic_arpabet": row.phonetic_arpabet,
        "context": bundle.to_payload(),
        "context_flat": best.text if best else None,
        "affix": affix,
        "xiangxing": xiangxing,
        "collocations": collocations,
        "derived_gloss": (
            {"gloss": derived.gloss, "source_sentence_id": derived.source_sentence_id}
            if derived
            else None
        ),
        "tier": await assign_tier(db, vocabulary_item_id, has_context=bundle.has_context),
        "llm_entry": {
            "word": row.word,
            "pos": row.pos,
            "meaning_cn": gloss,
            "context": best.text if best else None,
            "affix_hint": (affix or {}).get("chain"),
            # 库内真实同族候选。空列表是**合法且常见**的结果（专有名词/缩写），
            # prompt 据此要求模型交空数组，而不是编一个继任词。见 family_candidates。
            "family_candidates": await family_candidates(
                db, row.word, vocabulary_item_id=vocabulary_item_id
            ),
            # 形近易混候选（确定性）。空列表同样是合法输入 —— 库内没有形近词时
            # 不该硬凑一个对照词。learner_confused_with 是学习者自报的混淆词，
            # 属其自身经验，**不要求**库内存在，但会被显式标成学习者声明。
            "confusable_candidates": await confusable_candidates(db, row.word),
            "learner_confused_with": learner_confused_with,
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


# 屈折/派生后缀，长 → 短。剥到不能再剥为止，得到「词干」。
# 刻意**只**用这个封闭清单，不用 Porter/Snowball：那些算法会把 `unhappiness`
# 一路剥到 `unhapp`，制造出噪声前缀。词干只用来找**候选**，最终仍由
# `resolve_family` 校验，所以过一点也无妨。
_INFLECTIONAL_SUFFIXES: tuple[str, ...] = (
    "iness", "ingly", "edly", "ing", "ies", "ied", "ers", "est", "ness",
    "tion", "sion", "ment", "able", "ible", "less", "ful", "ous", "ive",
    "ise", "ize", "ity", "er", "ed", "ly", "al", "es", "s",
)
# 刻意**不含** `y`：`happy` 剥掉 y 变成 `happ`，于是 `happen`/`happen to`
# 全被当成同族词（实测）。`y` 在这些派生里是词干的一部分，不是屈折。
# 少给几个候选只是让模型多交一次空数组；给错候选会直接污染 family。

# 词干短于此值就没有可用前缀信号（`CD`/`DJ`/`Dr` 这类缩写）。
_MIN_STEM_LEN = 4


def _stem(word: str) -> str:
    """确定性词干：按后缀长度从长到短剥，剥到不再变化为止。"""
    w = word.lower().strip()
    changed = True
    while changed:
        changed = False
        for suffix in _INFLECTIONAL_SUFFIXES:
            if len(w) - len(suffix) >= _MIN_STEM_LEN and w.endswith(suffix):
                w = w[: -len(suffix)]
                changed = True
                break
    return w


async def family_candidates(
    db: Any,
    word: str,
    *,
    vocabulary_item_id: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """库里**真实存在**的同族候选词（确定性，不问 LLM）。

    为什么需要这个：`FAMILY_TRACEABLE` 要求 family 成员可在库内检索到，但 LLM
    无从得知库里有哪些词，于是会去提 `ravine`/`canyon` 这类**英语里真实、库里没有**
    的词 —— 100 词试跑里它成了唯一的拒收来源（实测 2/14）。
    与其放宽门禁（那等于放弃「family 不得编造」的原意），不如**把清单给它**：
    模型只在候选里挑，挑不出就交空数组。

    两个信号取并集（都确定性）：

    1. **词干前缀** —— 剥掉屈折后缀后同前缀，且比词干长。`valley` → `valleys`。
    2. **同词根** —— `vocabulary_affixes.root` 相同。

    专有名词与缩写（Canada / CD / December）**本来就没有同族词**，此时返回空
    列表、由 prompt 明确要求交空数组 —— 这比逼模型编一个继任词更诚实。
    """
    from sqlalchemy import text

    target = (word or "").strip().lower()
    if not target:
        return []

    found: dict[str, dict[str, Any]] = {}

    stem = _stem(target)
    if len(stem) >= _MIN_STEM_LEN:
        rows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(v.word)) v.id, v.word, v.meaning_cn
            FROM vocabulary_items v
            WHERE lower(v.word) LIKE :prefix || '%'
              AND length(v.word) > :plen
              AND lower(v.word) <> :target
              -- 库里混有 `care about` / `happen to do sth.` 这类**短语**。
              -- 家族词必须是单个词，否则模型会挑中短语当派生词。
              AND v.word !~ '\\s'
            ORDER BY lower(v.word), length(v.word), v.id
            LIMIT :limit
            """
                ),
                {"prefix": stem, "plen": len(stem), "target": target, "limit": limit},
            )
        ).all()
        for r in rows:
            found.setdefault(r.word.lower(), {"word": r.word, "meaning_cn": r.meaning_cn})

    if vocabulary_item_id:
        rows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(v.word)) v.id, v.word, v.meaning_cn
            FROM vocabulary_affixes a
            JOIN vocabulary_items v ON v.id = a.vocabulary_item_id
            WHERE lower(a.root) = (
                    SELECT lower(a2.root) FROM vocabulary_affixes a2
                    WHERE a2.vocabulary_item_id = :vid
                      AND btrim(coalesce(a2.root, '')) <> ''
                    LIMIT 1
                )
              AND v.id <> :vid
              AND lower(v.word) <> :target
              AND v.word !~ '\\s'
            ORDER BY lower(v.word), v.id
            LIMIT :limit
            """
                ),
                {"vid": vocabulary_item_id, "target": target, "limit": limit},
            )
        ).all()
        for r in rows:
            found.setdefault(r.word.lower(), {"word": r.word, "meaning_cn": r.meaning_cn})

    # 前缀信号先入，词根信号后补；各自 SQL 内已定序，这里保持插入序 = 确定性。
    return list(found.values())[:limit]


def _edit_distance_le(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超过 ``cap`` 提前返回 ``cap + 1``。

    提前截断是因为这里只关心「是否形近」，不是精确距离 —— 全量词表两两比较
    时这个截断省掉大量无谓的计算。
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(val)
            if val < best:
                best = val
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# 形近判定：长度差 ≤1 且**编辑距离 ≤1**。
#
# 上限从 2 收紧到 1 是被 100 词试跑的数据逼出来的（2026-10-05）：那轮产出 115 条
# 易混对，按距离拆开看 —— 距离=1 的 63 条**实测 100% 是真易混**
# （chance/change、honour/honor、valley/alley、gold/cold、beer/bee、
#  prevent/present、shake/shade、Germany/German…），而距离≥2 的 52 条**多数是噪声**
# （offer/coffee、influence/influenza、honour/colour、boss/Boys、Paris/parish）。
#
# 代价是丢掉 `retire/entire` 这类少数真易混（距离 2）；收益是精度从约 45% 提到
# 接近 100%。**易混点宁可少收也不误收** —— 收一条不混淆的对照规则，学生会拿它
# 当真的记一辈子，而它本来什么也没教会。
_CONFUSABLE_MAX_EDIT = 1
_CONFUSABLE_MIN_LEN = 4


async def confusable_candidates(
    db: Any,
    word: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """库里与 ``word`` **形近**的真实词（确定性，不问 LLM）。

    为什么需要：spec §五 ⚠️易混点 与 §九（"我总把 affect 和 effect 搞混"
    提升为最高优先级）都要求引擎讲清易混词，但模型无从得知库里有哪些词，
    凭英语世界知识作答会去编造「其实不混淆」的对照词。

    判据只有一条：**形近**（长度差 ≤1 且编辑距离 ≤1）。`affect`/`effect`
    只差首字母、`adapt`/`adopt` 差一个字母、`desert`/`dessert` 插一个字母
    —— 全部命中。

    **覆盖是局部的**：音近、同义近义、跨词性混淆本判据抓不到（`retire`/`entire`
    这类距离 2 的真易混也会被丢掉）。这是诚实边界，不假装覆盖全 —— 门禁
    ``CONFUSABLES_GROUNDED`` 只要求「给出的都能在候选里查到」，
    **不要求**「该有的都找到了」。
    """
    from sqlalchemy import text

    target = (word or "").strip().lower()
    if len(target) < _CONFUSABLE_MIN_LEN:
        return []
    rows = (
        await db.execute(
            text(
                """
        SELECT DISTINCT ON (lower(v.word)) v.word, v.meaning_cn, v.pos
        FROM vocabulary_items v
        WHERE lower(v.word) <> :target
          AND length(v.word) BETWEEN :lo AND :hi
          AND v.word ~ '^[A-Za-z][A-Za-z-]*$'
        ORDER BY lower(v.word)
        """
            ),
            {
                "target": target,
                "lo": len(target) - 1,
                "hi": len(target) + 1,
            },
        )
    ).all()
    out: list[tuple[int, str, dict[str, Any]]] = []
    for r in rows:
        w = (r.word or "").strip().lower()
        dist = _edit_distance_le(target, w, _CONFUSABLE_MAX_EDIT)
        if dist <= _CONFUSABLE_MAX_EDIT:
            out.append((dist, w, {"word": r.word, "meaning_cn": r.meaning_cn, "pos": r.pos}))
    # 距离近的在前；同距离按单词序，保证确定性
    out.sort(key=lambda t: (t[0], t[1]))
    return [d for _dist, _w, d in out[:limit]]


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
    "confusable_candidates",
    "family_candidates",
    "resolve_family",
]
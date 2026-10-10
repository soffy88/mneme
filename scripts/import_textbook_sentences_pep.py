#!/usr/bin/env python3
"""scripts/import_textbook_sentences_pep.py — 把人教社英语教材 OCR 句落库。

输入：`reports/vocab_memory_p0/pep_ocr_sentences.json`（`ocr_pep_pages.py` 的
输出，已经过句子门禁筛选）。落库到 `textbook_sentences` +
`textbook_sentence_occurrences`（alembic `pep1a2b3c4d5e`），并给 `textbooks` /
`books` 补上这 3 本英语教材。

## 这一步解的是实测出来的真瓶颈

核心 2,761 单词口径（2026-10-06 实测）：有可用释义 2,732，其中**只有 2,066 个
词有语境句** —— 另外 **666 个词**被 `retrieve_context` 挡在门外（它在
`has_context=False` 时提前返回，`to_payload()` 里连 `meaning` 字段都没有）。
缺口不在释义（已从 776 补到 29），在**真实语境句**。

为什么教材句是那 666 个词唯一合格的来源：`retrieve_context` 的 Context Priority
是**教材优先于 NCE**（tier 1/2 > tier 3），而 EchoType 那批词表的英文例句实测
**是生成的**（`senior-high` 与 `gaokao2026` 逐字节相同，且 `cet4` 有 2,015 条与
它完全一致），按红线一律不进 `context_evidence`。教材正文是有出处、可回溯、
且不是生成的。

## 词→句关联复用 NCE 的 `VocabularyExtractor`

**不自己写分词器**：`scripts/nce_importer/extractor.py` 的 `VocabularyExtractor`
已经处理了单词 + 短语（n-gram）两种形态，并给出 `token_start`/`token_end`/
`occurrence_index`。重写一个必然出现两套口径不一致的 `occurrence_index`，
那是给未来的自己埋雷。

## 幂等

`sentence_id` 由 `(textbook_id, page, sentence_index)` **确定性**生成，
关联表按 `uq_textbook_sentence_occurrence` + `ON CONFLICT DO NOTHING`。
重跑不会产生重复行。

## 版权

按人决策，教材正文直接接入。每行带 `license_status='unlicensed'`，因此
**按整本教材下架不需要数据迁移**：
`DELETE FROM textbook_sentences WHERE textbook_id = 'pep-g7b'`（CASCADE 会
连带删掉关联行）。取得授权后改这一个字段即可。

    docker compose exec api python scripts/import_textbook_sentences_pep.py
    docker compose exec api python scripts/import_textbook_sentences_pep.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SRC = (
    _REPO_ROOT / "reports" / "vocab_memory_p0" / "pep_ocr_sentences.json"
)
COLLECTION = "core-exam-zhongkao-gaokao-k12"
SOURCE_TAG = "PEP_OCR_RAPIDOCR"
LICENSE_STATUS = "unlicensed"

# 与 `fetch_pep_pages.py` 的 slug 一一对应。
def _b(slug: str, grade: str, edition: str, name: str, pep_id: str) -> dict[str, str]:
    return {
        "textbook_id": f"pep-en-{slug}",
        "grade": grade,
        "edition": edition,
        "book_name": name,
        "pep_book_id": pep_id,
    }


BOOKS: dict[str, dict[str, str]] = {
    "g7a": _b("g7a", "G7", "上册", "义务教育教科书 英语 七年级上册", "1312001101241"),
    "g7b": _b("g7b", "G7", "下册", "义务教育教科书 英语 七年级下册", "1312001102241"),
    "g8a": _b("g8a", "G8", "上册", "义务教育教科书 英语 八年级上册", "1312001201251"),
    "g8b": _b("g8b", "G8", "下册", "义务教育教科书 英语 八年级下册", "1312001202251"),
    "g9a": _b("g9a", "G9", "上册", "义务教育教科书 英语 九年级上册", "1312001301261"),
    "g9all": _b("g9all", "G9", "全一册", "义务教育教科书 英语 九年级全一册", "1312001303141"),
    "h1": _b("h1", "H1", "必修第一册", "普通高中教科书 英语 必修第一册", "1412001121191"),
    "h2": _b("h2", "H1", "必修第二册", "普通高中教科书 英语 必修第二册", "1412001122191"),
    "h3": _b("h3", "H1", "必修第三册", "普通高中教科书 英语 必修第三册", "1412001123191"),
    "hs1": _b("hs1", "H2", "选择性必修第一册", "普通高中教科书 英语 选择性必修第一册", "1412001127191"),
    "hs2": _b("hs2", "H2", "选择性必修第二册", "普通高中教科书 英语 选择性必修第二册", "1412001128201"),
    "hs3": _b("hs3", "H2", "选择性必修第三册", "普通高中教科书 英语 选择性必修第三册", "1412001129201"),
    "hs4": _b("hs4", "H2", "选择性必修第四册", "普通高中教科书 英语 选择性必修第四册", "1412001130201"),
}


def _norm_for_id(text: str) -> str:
    """句 ID 用的归一化形式：压空白 + 小写。

    只为**稳定身份**，不用于展示 —— 展示用 `english_text` 原样。
    """
    return " ".join(text.split()).lower()


def sentence_id(textbook_id: str, page: int, text: str) -> str:
    """确定性句 ID —— 由 ``(textbook_id, page, 句文本)`` 哈希而来。

    ⚠️ **不能**用 ``sentence_index`` 做 ID。踩过的坑：门禁收紧后同一页保留的句子
    变少（比如 g7b 从 435 降到 333），index 全体错位，于是 `ON CONFLICT DO
    NOTHING` 一个都匹配不上 —— 被新门禁拒掉的 ~1,200 句会**留在库里继续被
    tier 2 取用**。用句文本做哈希后，「同一句」在任何门禁版本下都是同一个 id，
    重新筛选天然幂等。

    不含随机数、不含时间戳：重跑必须得到同一个 id。
    """
    raw = f"{textbook_id}|{page}|{_norm_for_id(text)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"pep-{digest}"


async def run(apply: bool, limit: int | None) -> dict[str, Any]:
    from sqlalchemy import text

    from obase.db import SessionLocal

    from nce_importer.extractor import VocabularyExtractor

    data = json.loads(DEFAULT_SRC.read_text(encoding="utf-8"))
    rows = data["sentences"]
    if limit:
        rows = rows[:limit]

    unknown = sorted({r["book"] for r in rows} - set(BOOKS))
    if unknown:
        raise SystemExit(f"OCR 结果含未知教材 slug：{unknown}")

    # 每本按出现顺序编号 —— sentence_index 即该句在全书里的序号。
    counters: dict[str, int] = {b: 0 for b in BOOKS}
    planned: list[dict[str, Any]] = []
    for r in rows:
        slug = r["book"]
        idx = counters[slug]
        counters[slug] += 1
        planned.append(
            {
                "id": sentence_id(BOOKS[slug]["textbook_id"], int(r["page"]), r["text"]),
                "textbook_id": BOOKS[slug]["textbook_id"],
                "page": int(r["page"]),
                "n_boxes": r.get("n_boxes"),
                "min_score": r.get("min_score"),
                "sentence_index": idx,
                "english_text": r["text"],
            }
        )

    # 本次输入覆盖到的教材 —— 只对这些教材做「以本次为准」的清理。
    # 没出现在输入里的教材（例如还在下载中的高中册）**不动**，否则半成品输入
    # 会把已入库的数据删掉。
    touched = {p["textbook_id"] for p in planned}

    # 词表：只关联**核心范围**里的词，与既有 NCE 关联同口径。
    vocab_by_norm: dict[str, str] = {}
    phrases: set[str] = set()
    async with SessionLocal() as db:
        vrows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(btrim(v.word)))
                   v.id, lower(btrim(v.word)) AS w
            FROM vocabulary_items v
            JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
            WHERE m.collection_id = :coll AND v.word ~ '^[A-Za-z][A-Za-z'' -]*$'
            ORDER BY lower(btrim(v.word)), v.id
            """
                ),
                {"coll": COLLECTION},
            )
        ).all()
        for r in vrows:
            norm = " ".join(r.w.split())
            vocab_by_norm[norm] = r.id
            if " " in norm:
                phrases.add(norm)

    extractor = VocabularyExtractor(existing_phrases=phrases)

    # `TokenOccurrence` 只带 `normalized_form`，**没有** vocabulary_item_id ——
    # NCE 那条链是由 `resolver.py` 把它解析成 id 的。这里不引入 resolver
    # （它会顺带「新建」词条，而我们只想关联既有词），直接按 normalized_form
    # 查表：查不到就是句子里出现了词表外的词，跳过即可。
    occ_rows: list[tuple[str, str, int, int | None, int | None]] = []
    words_seen: set[str] = set()
    unmatched_tokens = 0
    for p in planned:
        ext = extractor.extract(p["english_text"])
        for i, occ in enumerate(ext.occurrences):
            vid = vocab_by_norm.get(occ.normalized_form)
            if vid is None:
                unmatched_tokens += 1
                continue
            occ_rows.append((p["id"], vid, i, occ.token_start, occ.token_end))
            words_seen.add(vid)

    sent_written = occ_written = book_written = pruned = 0
    if apply:
        async with SessionLocal() as db:
            # 「以本次输入为准」：删掉本次覆盖教材里**已不在输入中**的句。
            # 不做这一步的话，门禁收紧后被拒的旧句会留在库里继续被 tier 2 取用
            # —— 而它们的句子 id 是按内容哈希的，`ON CONFLICT DO NOTHING` 拦不住
            # 这种「多出来的旧行」。关联行随 textbook_sentences ON DELETE CASCADE 走。
            #
            # 只清理 `touched`（本次输入覆盖到的教材）：还在下载中的册子不出现在
            # 输入里，清理它就会把已入库的句子误删。
            #
            # 用 `!= ALL(:ids)` 而不是「先全删再全插」：后者每次跑都产生
            # 删除+插入的churn，且报告里的「已写库」行数永远等于全量，看不出
            # 幂等。这样写之后，重复跑一次应该是「清理 0 / 写入 0」。
            for tid in sorted(touched):
                ids = [q["id"] for q in planned if q["textbook_id"] == tid]
                if not ids:
                    continue
                res = await db.execute(
                    text(
                        """
                    DELETE FROM textbook_sentences
                    WHERE textbook_id = :t AND NOT (id = ANY(CAST(:ids AS text[])))
                    """
                    ),
                    {"t": tid, "ids": list(ids)},
                )
                pruned += res.rowcount or 0

            for slug, meta in BOOKS.items():
                res = await db.execute(
                    text(
                        """
                    INSERT INTO textbooks (id, subject, grade, edition, book_name)
                    VALUES (:id, 'english', :grade, :edition, :name)
                    ON CONFLICT (id) DO NOTHING
                    """
                    ),
                    {
                        "id": meta["textbook_id"],
                        "grade": meta["grade"],
                        "edition": meta["edition"],
                        "name": meta["book_name"],
                    },
                )
                book_written += res.rowcount or 0
                res = await db.execute(
                    text(
                        """
                    INSERT INTO books (id, textbook_id, title, status)
                    VALUES (:id, :tid, :title, 'published')
                    ON CONFLICT (id) DO NOTHING
                    """
                    ),
                    {
                        "id": f"book-{meta['textbook_id']}",
                        "tid": meta["textbook_id"],
                        "title": meta["book_name"],
                    },
                )
                book_written += res.rowcount or 0

            for p in planned:
                res = await db.execute(
                    text(
                        """
                    INSERT INTO textbook_sentences
                        (id, textbook_id, page_number, n_boxes, min_score,
                         sentence_index, english_text, chinese_text, source,
                         license_status)
                    VALUES (:id, :tid, :page, :nb, :ms, :si, :en, NULL, :src, :lic)
                    ON CONFLICT (id) DO NOTHING
                    """
                    ),
                    {
                        "id": p["id"],
                        "tid": p["textbook_id"],
                        "page": p["page"],
                        "nb": p["n_boxes"],
                        "ms": p["min_score"],
                        "si": p["sentence_index"],
                        "en": p["english_text"],
                        "src": SOURCE_TAG,
                        "lic": LICENSE_STATUS,
                    },
                )
                sent_written += res.rowcount or 0

            for sid, vid, oi, ts, te in occ_rows:
                res = await db.execute(
                    text(
                        """
                    INSERT INTO textbook_sentence_occurrences
                        (id, sentence_id, vocabulary_item_id, occurrence_index,
                         token_start, token_end)
                    VALUES (:id, :sid, :vid, :oi, :ts, :te)
                    ON CONFLICT (sentence_id, vocabulary_item_id, occurrence_index)
                    DO NOTHING
                    """
                    ),
                    {
                        "id": f"{sid}#{oi}",
                        "sid": sid,
                        "vid": vid,
                        "oi": oi,
                        "ts": ts,
                        "te": te,
                    },
                )
                occ_written += res.rowcount or 0
            await db.commit()

    return {
        "summary": {
            "ocr_sentences": len(rows),
            "planned_sentences": len(planned),
            "planned_occurrences": len(occ_rows),
            "distinct_vocab_linked": len(words_seen),
            "tokens_not_in_wordlist": unmatched_tokens,
            "applied": apply,
            "books_written": book_written,
            "pruned_stale": pruned,
            "sentences_written": sent_written,
            "occurrences_written": occ_written,
        },
        "per_book_sentences": counters,
        "vocab_sample": sorted(words_seen)[:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="人教社英语教材 OCR 句 → textbook_sentences")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()

    if not DEFAULT_SRC.exists():
        print(f"未找到 {DEFAULT_SRC}，先跑 ocr_pep_pages.py", file=sys.stderr)
        raise SystemExit(1)

    rep = asyncio.run(run(args.apply, args.limit or None))
    s = rep["summary"]
    print(f"OCR 句子            {s['ocr_sentences']}")
    print(f"计划入库句          {s['planned_sentences']}  {rep['per_book_sentences']}")
    print(f"词→句关联           {s['planned_occurrences']}")
    print(f"覆盖词数            {s['distinct_vocab_linked']}")
    if s["applied"]:
        print(
            f"已写库              清理旧句 {s['pruned_stale']} / 教材 {s['books_written']}"
            f" / 句 {s['sentences_written']} / 关联 {s['occurrences_written']}"
        )
    else:
        print("[dry-run] 不写库")


if __name__ == "__main__":
    main()
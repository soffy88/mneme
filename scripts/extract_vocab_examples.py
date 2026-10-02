"""P0.3 从 NCE 课文确定性挖掘 vocabulary_items.example_sentence。

为什么先挖例句再生成释义：
`oprim._vocab_gloss_generate` 的契约要求「例句由调用方从语料库确定性抽取，
不是 LLM 编的」，且 prompt 要求「最贴合**该例句语境**的中文释义」。没有例句就
没有语境可贴合，多义词必错（bank = 河岸 / 银行）。本脚本是该契约的前置步骤。

数据来源（全部已有，零外部依赖）：
    vocabulary_items
      ← vocabulary_collection_memberships (CORE_EXAM scope, 3,369 词)
      ← sentence_vocabulary_occurrences
      ← timed_sentences  (NCE 课文 13,017 条双语对齐句)

排序规则（确定性，可重复执行得到同一结果）：
  1. 句长分层：30–119 字最佳 → 20–29 或 120–160 → 其余非空兜底
  2. occurrence_index 升序（课文首次出现）
  3. sentence_id 升序（稳定 tie-break）

**与原 spec 的一处偏差（须知）**：spec 写「中考/高考教材优先」，但实测
`timed_sentences` 全部 559 个 lesson 都是 NCE（《新概念英语》lesson_key 形如
`001&002.Excuse Me`），且没有任何句子带中考/高考来源标注（lessons.book_id 与
books 表无交集）。故该优先级无法实现，改为按上述可用信号排序。

只写 example_sentence IS NULL 的行，天然幂等；不覆盖任何已有值。

    docker compose exec api python scripts/extract_vocab_examples.py            # dry-run
    docker compose exec api python scripts/extract_vocab_examples.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"

# 每个词的候选例句打分。tier 越小越优先。
_CANDIDATE_SQL = text(
    """
    WITH target AS (
        SELECT v.id, v.word
        FROM vocabulary_items v
        JOIN vocabulary_collection_memberships m
          ON m.vocabulary_item_id = v.id
        WHERE m.collection_id = :collection
          AND v.example_sentence IS NULL
          AND coalesce(v.example_sentence, '') = ''
    ),
    cand AS (
        SELECT t.id AS vid, t.word,
               ts.id AS sid,
               ts.english_text AS sentence,
               o.occurrence_index AS occ,
               length(ts.english_text) AS slen,
               CASE
                 WHEN length(ts.english_text) BETWEEN 30 AND 119 THEN 0
                 WHEN length(ts.english_text) BETWEEN 20 AND  29 THEN 1
                 WHEN length(ts.english_text) BETWEEN 120 AND 160 THEN 1
                 ELSE 2
               END AS tier
        FROM target t
        JOIN sentence_vocabulary_occurrences o ON o.vocabulary_item_id = t.id
        JOIN timed_sentences ts ON ts.id = o.sentence_id
        WHERE ts.english_text IS NOT NULL
          AND btrim(ts.english_text) <> ''
    )
    SELECT vid, word, sid, sentence, occ, slen, tier,
           row_number() OVER (
               PARTITION BY vid ORDER BY tier ASC, occ ASC, sid ASC
           ) AS rn
    FROM cand
    """
)

_SUMMARY_SQL = text(
    """
    WITH target AS (
        SELECT v.id
        FROM vocabulary_items v
        JOIN vocabulary_collection_memberships m
          ON m.vocabulary_item_id = v.id
        WHERE m.collection_id = :collection
          AND coalesce(v.example_sentence, '') = ''
    )
    SELECT
      (SELECT count(*) FROM target)                                            AS need,
      (SELECT count(*) FROM target t WHERE EXISTS (
          SELECT 1 FROM sentence_vocabulary_occurrences o
          JOIN timed_sentences ts ON ts.id = o.sentence_id
          WHERE o.vocabulary_item_id = t.id
            AND ts.english_text IS NOT NULL AND btrim(ts.english_text) <> ''
      ))                                                                      AS fillable
    """
)


async def run(collection: str, apply: bool) -> None:
    params = {"collection": collection}
    async with SessionLocal() as db:
        need, fillable = (await db.execute(_SUMMARY_SQL, params)).one()
        print(f"目标范围 collection={collection}")
        print(f"  尚缺例句的词      = {need}")
        print(f"  其中有可用课文句  = {fillable}")
        print(f"  本轮可填充        = {min(need, fillable)}")
        print(f"  仍无语境(将跳过)  = {max(0, need - fillable)}")

        picked = (
            await db.execute(_CANDIDATE_SQL, params)
        ).mappings().all()
        best = [r for r in picked if r["rn"] == 1]
        print(f"  候选句命中(去重后) = {len(best)}")

        if not best:
            print("无可填充项，退出")
            return

        tiers: dict[int, int] = {}
        for r in best:
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        print("  按句长分层分布: " + ", ".join(f"tier{k}={v}" for k, v in sorted(tiers.items())))

        if not apply:
            print(f"\n[dry-run] 将更新 {len(best)} 行的 example_sentence。未落库。")
            print("  样例:")
            for r in best[:5]:
                print(f"    {r['word']:14s} tier{r['tier']} len{r['slen']:>4} {r['sentence'][:70]}")
            return

        # 按 id 逐条 UPDATE（不用 word —— word 在本表不唯一）。语义条件保留在
        # WHERE 里，天然幂等且不会覆盖并发写入的值。
        n = 0
        for r in best:
            await db.execute(
                text(
                    "UPDATE vocabulary_items SET example_sentence = :s, updated_at = :now "
                    "WHERE id = :vid AND coalesce(example_sentence, '') = ''"
                ),
                {"s": r["sentence"], "now": datetime.now(timezone.utc), "vid": r["vid"]},
            )
            n += 1
            if n % 500 == 0:
                await db.commit()
                print(f"  …已更新 {n}/{len(best)}")
        await db.commit()

        done = (
            await db.execute(
                text(
                    "SELECT count(*) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.example_sentence,'') <> ''"
                ),
                {"c": collection},
            )
        ).scalar()
        print(f"\n完成：本次更新 {n} 行；范围内已有例句 {done} 词")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--collection", default=CORE_COLLECTION)
    args = parser.parse_args()
    asyncio.run(run(args.collection, apply=args.apply))
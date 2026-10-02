"""P0.2 固化 CORE_EXAM_VOCAB_SCOPE（中高考核心词范围）。

定义（2026-10-02 人决策）：核心词 = 中考 ∩ 高考 ∩ 教材同步。

    ZHONGKAO ∩ GAOKAO ∩ K12_SYNC

为什么是交集而不是并集（实测，非推测）：

    ∪ (中考∪高考∪教材)  = 20,173 词，其中仅 5,601 (27.8%) 有教材语境
    ∩ (中考∩高考∩教材)  =  3,369 词，其中   2,308 (68.5%) 有教材语境

选 ∩ 的三个理由：
  1. 命中产品侧「核心 3000~4000 词」的目标区间；
  2. 语境覆盖率高 2.5 倍 —— 释义生成必须有真实例句才可信
     （见 oprim._vocab_gloss_generate 契约：例句不得由 LLM 编造）；
  3. 并集里 72% 无语境，若强行回填就是 P0.1 刚修掉的「无上下文猜义项」污染，
     且规模放大 6 倍。

产出：一条 vocabulary_collections 记录（kind=DERIVED / scope=CORE_EXAM）
+ 3,369 条 vocabulary_collection_memberships。membership id 用 uuid5 确定性
派生（同 import_english_k12_vocab.py 的约定），可反复执行。

幂等：collection 用 on_conflict_do_update，membership 用
on_conflict_do_nothing(constraint='uq_vocab_membership')。

    docker compose exec api python scripts/freeze_core_exam_vocab.py --dry-run
    docker compose exec api python scripts/freeze_core_exam_vocab.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from services.models import VocabularyCollection, VocabularyCollectionMembership  # noqa: E402

# 核心范围的三个来源 scope
SCOPES = ("ZHONGKAO", "GAOKAO", "K12_SYNC")

COLLECTION_ID = "core-exam-zhongkao-gaokao-k12"
COLLECTION_TITLE = "中高考核心词（中考∩高考∩教材同步）"

# 与 import_english_k12_vocab.get_vid 同样的命名空间占位，保持全仓一致。
_MEMBERSHIP_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def membership_id(collection_id: str, vocabulary_item_id: str) -> str:
    """确定性 membership id —— 同 import_english_k12_vocab.py 的派生方式。"""
    return str(uuid.uuid5(_MEMBERSHIP_NS, f"mneme://membership/{collection_id}/{vocabulary_item_id}"))


# 交集：出现在全部 SCOPES 里的 vocabulary_item。distinct 是必须的——同一词可
# 命中多个考纲 collection（高考有 47 个 collection）。
_INTERSECT_SQL = text(
    """
    SELECT m.vocabulary_item_id
    FROM vocabulary_collection_memberships m
    JOIN vocabulary_collections c ON c.id = m.collection_id
    WHERE c.scope = ANY(:scopes)
    GROUP BY m.vocabulary_item_id
    HAVING count(DISTINCT c.scope) = :n_scopes
    ORDER BY m.vocabulary_item_id
    """
)

# 诊断用：各 scope 词数 + 有无语境，用于把真实覆盖率写进报告而不是拍脑袋。
_DIAG_SQL = text(
    """
    WITH s AS (
        SELECT m.vocabulary_item_id AS vid, c.scope
        FROM vocabulary_collection_memberships m
        JOIN vocabulary_collections c ON c.id = m.collection_id
        WHERE c.scope = ANY(:scopes)
    ),
    inter AS (SELECT vid FROM s GROUP BY vid HAVING count(DISTINCT scope) = :n_scopes)
    SELECT
      (SELECT count(*) FROM inter)                                        AS inter_total,
      (SELECT count(*) FROM (SELECT DISTINCT vid FROM s) u)               AS union_total,
      (SELECT count(*) FROM inter i WHERE EXISTS (
          SELECT 1 FROM sentence_vocabulary_occurrences o
          WHERE o.vocabulary_item_id = i.vid))                            AS inter_with_ctx,
      (SELECT count(*) FROM (SELECT DISTINCT vid FROM s) u WHERE EXISTS (
          SELECT 1 FROM sentence_vocabulary_occurrences o
          WHERE o.vocabulary_item_id = u.vid))                            AS union_with_ctx,
      (SELECT count(*) FROM inter i JOIN vocabulary_items v ON v.id = i.vid
         WHERE v.example_sentence IS NOT NULL AND v.example_sentence <> '') AS inter_has_example,
      (SELECT count(*) FROM inter i JOIN vocabulary_items v ON v.id = i.vid
         WHERE v.meaning_cn IS NOT NULL)                                   AS inter_has_gloss,
      (SELECT count(*) FROM inter i JOIN vocabulary_items v ON v.id = i.vid
         WHERE coalesce(v.phonetic_us, v.phonetic_uk, '') <> '')          AS inter_has_phonetic,
      (SELECT count(DISTINCT v.word) FROM inter i
         JOIN vocabulary_items v ON v.id = i.vid)                          AS inter_distinct_word
    """
)


async def collect(db) -> tuple[list[str], dict]:
    params = {"scopes": list(SCOPES), "n_scopes": len(SCOPES)}
    rows = (await db.execute(_INTERSECT_SQL, params)).scalars().all()
    diag = (await db.execute(_DIAG_SQL, params)).mappings().one()
    return list(rows), dict(diag)


async def run(apply: bool) -> None:
    async with SessionLocal() as db:
        vids, diag = await collect(db)
        print(f"核心范围 = {' ∩ '.join(SCOPES)}")
        for k, val in diag.items():
            print(f"  {k:24s} = {val}")
        if not vids:
            print("交集为空，终止（不做任何写入）")
            return

        # 同名不同行会让「核心词数」虚高；交集内若出现必须在写入前报出来。
        if diag["inter_total"] != diag["inter_distinct_word"]:
            print(
                f"  ⚠️ 交集内存在同名重复行：{diag['inter_total']} 行 / "
                f"{diag['inter_distinct_word']} 个不同词"
            )

        meta = {
            "definition": "intersection",
            "scopes": list(SCOPES),
            "definition_sql_hint": "GROUP BY vocabulary_item_id HAVING count(DISTINCT scope) = 3",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "counts": diag,
            "rationale": (
                "选交集而非并集：并集 20173 词仅 27.8% 有教材语境，交集 3369 词 "
                "68.5% 有语境；释义生成必须有真实例句，无语境不猜义项。"
            ),
        }

        if not apply:
            print(f"\n[dry-run] 将写入 collection 1 条 + memberships {len(vids)} 条。未落库。")
            return

        now = datetime.now(timezone.utc)
        stmt_c = insert(VocabularyCollection).values(
            id=COLLECTION_ID,
            kind="DERIVED",          # 非某一考纲的原始词表，而是派生集合
            scope="CORE_EXAM",
            title=COLLECTION_TITLE,
            stage="UNKNOWN",         # 跨学段（小学/初中/高中都有），无单一值
            publisher="mneme-derived",
            metadata_json=meta,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=[VocabularyCollection.id],
            # 用字面量而非 stmt_c.excluded.*：后者会在同一个表达式里引用尚未
            # 绑定的 stmt_c，运行时直接 UnboundLocalError。
            set_={
                "title": COLLECTION_TITLE,
                "metadata_json": meta,
                "updated_at": now,
            },
        )
        await db.execute(stmt_c)

        rows = [
            {
                "id": membership_id(COLLECTION_ID, vid),
                "collection_id": COLLECTION_ID,
                "vocabulary_item_id": vid,
            }
            for vid in vids
        ]
        # executemany + DO NOTHING：重复执行不产生新行，也不会因已存在而报错。
        for chunk_start in range(0, len(rows), 1000):
            chunk = rows[chunk_start : chunk_start + 1000]
            await db.execute(
                insert(VocabularyCollectionMembership)
                .values(chunk)
                .on_conflict_do_nothing(constraint="uq_vocab_membership")
            )

        await db.commit()

        n = (
            await db.execute(
                text("SELECT count(*) FROM vocabulary_collection_memberships WHERE collection_id = :cid"),
                {"cid": COLLECTION_ID},
            )
        ).scalar()
        print(f"\n完成：collection={COLLECTION_ID}，memberships 实际 {n} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))
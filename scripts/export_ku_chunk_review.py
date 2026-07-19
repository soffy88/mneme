"""导出 KU<->chunk 挂接候选供人工校订（W3 Part A→B 过渡，Book Engine 引用前置门）。

背景：A3 挂接命中率约 85%（1/20 词汇碰撞误判——embedding 分数分不出"对的0.78"
和"碰撞的0.78"），Book Engine 引用教材原文前，高风险挂接需人工确认
（ku_chunk_matches.verified，见迁移 c4d5e6f7a8ba）。

排序：exam_frequency='high' 优先（语料库里只有 4 个，真实使用数据不存在，
这是唯一有意义的先验信号）；其余按 rank=1 匹配分数**升序**——分数越低越可能
是错的，优先审最可能错的，而不是数量最多的"mid"频次桶（那个字段 99.5% 是
mid，几乎没有区分度）。

用法：
  python scripts/export_ku_chunk_review.py [--limit N] [--out path.csv]

输出 CSV（宽表，一行一个 KU，三个候选并排）：
  ku_id, ku_name, ku_description, exam_frequency,
  r1_chunk_id, r1_score, r1_page, r1_excerpt,
  r2_chunk_id, r2_score, r2_page, r2_excerpt,
  r3_chunk_id, r3_score, r3_page, r3_excerpt,
  correct_rank   <- 人工填：1/2/3=对应候选正确；0=三个都不对；留空=未审

审完用 scripts/apply_ku_chunk_review.py 把 correct_rank 写回
ku_chunk_matches.verified。
"""

from __future__ import annotations

import argparse
import asyncio
import csv

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings

EXCERPT_LEN = 150


def _flatten(text: str, length: int = EXCERPT_LEN) -> str:
    return text.replace("\n", " ").replace("\r", " ")[:length]


async def main(limit: int, out_path: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with factory() as db:
        # 已审过的（verified 非 NULL 状态，即已经处理过一次）不再重复导出
        rows = (
            await db.execute(
                sa_text("""
            SELECT ku.id, ku.name, ku.description, ku.exam_frequency,
                   kcm.rank, kcm.score, kcm.chunk_id, tc.page_number, tc.content
            FROM knowledge_units ku
            JOIN ku_chunk_matches kcm ON kcm.ku_id = ku.id
            JOIN textbook_chunks tc ON tc.id = kcm.chunk_id
            WHERE NOT EXISTS (
                SELECT 1 FROM ku_chunk_matches k2
                WHERE k2.ku_id = ku.id AND k2.verified = true
            )
            ORDER BY
                (ku.exam_frequency = 'high') DESC,
                (SELECT score FROM ku_chunk_matches r1
                 WHERE r1.ku_id = ku.id AND r1.rank = 1) ASC,
                ku.id, kcm.rank
        """)
            )
        ).fetchall()

    # 按 ku_id 分组，重组成宽表一行
    by_ku: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        if r.id not in by_ku:
            by_ku[r.id] = {
                "ku_id": r.id,
                "ku_name": r.name,
                "ku_description": r.description or "",
                "exam_frequency": r.exam_frequency,
                "candidates": {},
            }
            order.append(r.id)
        by_ku[r.id]["candidates"][r.rank] = {
            "chunk_id": r.chunk_id,
            "score": round(r.score, 4),
            "page": r.page_number,
            "excerpt": _flatten(r.content),
        }

    if limit:
        order = order[:limit]

    fieldnames = ["ku_id", "ku_name", "ku_description", "exam_frequency"]
    for rk in (1, 2, 3):
        fieldnames += [
            f"r{rk}_chunk_id",
            f"r{rk}_score",
            f"r{rk}_page",
            f"r{rk}_excerpt",
        ]
    fieldnames.append("correct_rank")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ku_id in order:
            entry = by_ku[ku_id]
            row = {
                "ku_id": entry["ku_id"],
                "ku_name": entry["ku_name"],
                "ku_description": entry["ku_description"],
                "exam_frequency": entry["exam_frequency"],
                "correct_rank": "",
            }
            for rk in (1, 2, 3):
                c = entry["candidates"].get(rk, {})
                row[f"r{rk}_chunk_id"] = c.get("chunk_id", "")
                row[f"r{rk}_score"] = c.get("score", "")
                row[f"r{rk}_page"] = c.get("page", "")
                row[f"r{rk}_excerpt"] = c.get("excerpt", "")
            writer.writerow(row)

    print(f"导出 {len(order)} 个待审 KU -> {out_path}")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=全部导出")
    parser.add_argument("--out", type=str, default="outputs/ku_chunk_review.csv")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.out))

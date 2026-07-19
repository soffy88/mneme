"""把人工校订结果（scripts/export_ku_chunk_review.py 导出的 CSV，correct_rank
列已填）写回 ku_chunk_matches.verified。

规则：
  correct_rank = 1/2/3 -> 对应 rank 的那一行 verified=true，同一 ku_id 的其他
                          行 verified=false（幂等，重复 apply 同一份 CSV 不变）。
  correct_rank = 0     -> 三个候选都不对，该 KU 全部 rank 的 verified=false
                          （明确"审过、但没有对的"，跟"还没审"用 verified_note
                          区分——见下方 note 写法）。
  correct_rank 留空    -> 跳过这一行，不改动（视为尚未审）。

用法：
  python scripts/apply_ku_chunk_review.py path/to/reviewed.csv [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings


async def main(csv_path: str, dry_run: bool) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    now = datetime.now(timezone.utc)
    n_verified = 0
    n_rejected = 0
    n_skipped = 0
    n_bad = 0

    async with factory() as db:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw = (row.get("correct_rank") or "").strip()
                ku_id = row["ku_id"]

                if raw == "":
                    n_skipped += 1
                    continue

                try:
                    correct_rank = int(raw)
                except ValueError:
                    print(f"  跳过（correct_rank 非法：{raw!r}）: {ku_id}")
                    n_bad += 1
                    continue

                if correct_rank not in (0, 1, 2, 3):
                    print(f"  跳过（correct_rank 超出 0-3：{raw!r}）: {ku_id}")
                    n_bad += 1
                    continue

                if not dry_run:
                    # 先全清，再按结果设置——幂等，重复 apply 同一份 CSV 结果不变
                    await db.execute(
                        sa_text(
                            "UPDATE ku_chunk_matches SET verified=false, verified_at=:now, "
                            "verified_note=:note WHERE ku_id=:ku_id"
                        ),
                        {
                            "now": now,
                            "ku_id": ku_id,
                            "note": "reviewed_no_correct_match"
                            if correct_rank == 0
                            else None,
                        },
                    )
                    if correct_rank != 0:
                        await db.execute(
                            sa_text(
                                "UPDATE ku_chunk_matches SET verified=true, verified_note='human_confirmed' "
                                "WHERE ku_id=:ku_id AND rank=:rank"
                            ),
                            {"ku_id": ku_id, "rank": correct_rank},
                        )

                if correct_rank == 0:
                    n_rejected += 1
                else:
                    n_verified += 1

            if not dry_run:
                await db.commit()

    print(
        f"完成：{n_verified} 个 KU 确认挂接，{n_rejected} 个 KU 三候选均不对，"
        f"{n_skipped} 个未审跳过，{n_bad} 行格式错误"
        + ("（--dry-run，未写库）" if dry_run else "")
    )
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, args.dry_run))

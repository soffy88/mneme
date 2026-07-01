"""清理 KU 悬空前置边（解卡新学路径）。

实证：5530 条前置边里仅 6 条是合法 KU id，3375 条其实是存了**中文名**（可按唯一名解析
回 id），2149 条真悬空。悬空/名式前置会静默卡住 daily-plan 新学路径（前置永远满足不了）。

清理：每条前置 → 已是合法 id 则留；唯一名可解析则换成 id；否则丢弃（真悬空/歧义）。
清理后建议再跑 backfill_ku_provenance 刷新 verified。

  python scripts/clean_ku_prerequisites.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg

from obase.config import settings


def _as_list(v):
    return [] if v is None else (json.loads(v) if isinstance(v, str) else list(v))


async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    try:
        rows = await conn.fetch("select id, name, prerequisites from knowledge_units")
        ids = {r["id"] for r in rows}
        # 唯一名 → id（重名的排除，避免歧义误解析）
        seen: dict[str, str] = {}
        dup: set[str] = set()
        for r in rows:
            if r["name"] in seen:
                dup.add(r["name"])
            seen.setdefault(r["name"], r["id"])
        name2id = {n: i for n, i in seen.items() if n not in dup}

        resolved = dropped = kept = 0
        updates = []
        for r in rows:
            prs = _as_list(r["prerequisites"])
            new_prs: list[str] = []
            changed = False
            for p in prs:
                if p in ids:
                    new_prs.append(p); kept += 1
                elif p in name2id:
                    new_prs.append(name2id[p]); resolved += 1; changed = True
                else:
                    dropped += 1; changed = True  # 真悬空/歧义 → 丢
            # 去重保序
            dedup = list(dict.fromkeys(new_prs))
            if changed or dedup != prs:
                updates.append((json.dumps(dedup, ensure_ascii=False), r["id"]))

        if not dry_run:
            B = 500
            for i in range(0, len(updates), B):
                await conn.executemany(
                    "update knowledge_units set prerequisites=$1::jsonb where id=$2",
                    updates[i:i + B])
    finally:
        await conn.close()
    print(f"完成 dry_run={dry_run}: 已是id保留 {kept}，名→id解析 {resolved}，"
          f"悬空丢弃 {dropped}，更新 KU {len(updates)}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(run(p.parse_args().dry_run))


if __name__ == "__main__":
    main()

"""存量 KU 溯源/可信度回填（item 2 的存量治理）。

12573 个存量 KU 是离线脚本绕过校验门灌的：verified=false、无 provenance。
真实 provenance（哪段原文/哪页）已不可追溯，但可做**可信度审计 + 标记**：
- 每个 KU 跑一遍确定性校验门 validate_curriculum_ku → 过门者 verified=true，
  未过门 verified=false 并记 gate_errors（待人工复核）。
- provenance 标记为 legacy_backfill（明确这些 KU 早于校验门、源文未留存）。
- ai_generated=true（均 LLM 抽取）。

这样把"0/12573 verified、无溯源"变成"X 可信 / Y 待核、全部有溯源标记"，
学习侧可据 verified 区分"过门可信"与"存疑"知识点。

  python scripts/backfill_ku_provenance.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

import asyncpg

from obase.config import settings
from services.ku_ingest_service import validate_curriculum_ku


def _as_list(v):
    if v is None:
        return []
    return json.loads(v) if isinstance(v, str) else list(v)


async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    now = datetime.now(timezone.utc).isoformat()
    try:
        known = {r["id"] for r in await conn.fetch("select id from knowledge_units")}
        rows = await conn.fetch(
            "select id, name, description, prerequisites, difficulty from knowledge_units")
        stats = {"verified": 0, "flagged": 0}
        reasons: Counter = Counter()
        BATCH = 500
        updates = []
        for r in rows:
            ku = {
                "id": r["id"], "name": r["name"], "description": r["description"],
                "prerequisites": _as_list(r["prerequisites"]),
                "difficulty": r["difficulty"] if r["difficulty"] is not None else 0.5,
            }
            valid, errors = validate_curriculum_ku(ku, known_ku_ids=known)
            prov = {"source": "legacy_backfill", "backfilled_at": now, "gate_passed": valid}
            if not valid:
                prov["gate_errors"] = errors[:4]
                for e in errors:
                    reasons[e.split(":")[0].split(" (")[0]] += 1
            stats["verified" if valid else "flagged"] += 1
            updates.append((valid, json.dumps(prov, ensure_ascii=False), r["id"]))

        if not dry_run:
            for i in range(0, len(updates), BATCH):
                await conn.executemany(
                    "update knowledge_units set verified=$1, ai_generated=true, "
                    "provenance=coalesce(provenance,'{}'::jsonb)||$2::jsonb where id=$3",
                    updates[i:i + BATCH])
                print(f"  已写 {min(i + BATCH, len(updates))}/{len(updates)}")
    finally:
        await conn.close()
    print(f"\n完成 dry_run={dry_run}: 总 {stats['verified'] + stats['flagged']}，"
          f"过门可信 {stats['verified']}，待核 {stats['flagged']}")
    if reasons:
        print("  待核原因 top:", dict(reasons.most_common(6)))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    asyncio.run(run(p.parse_args().dry_run))


if __name__ == "__main__":
    main()

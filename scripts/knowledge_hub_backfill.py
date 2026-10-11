#!/usr/bin/env python3
"""Knowledge Hub backfill: chunk embeddings + KU→chunk inferred matches (W3 A2/A3 repeatable).

    # 1) vectors for chunks ingested while the embedder was down (embedding IS NULL)
    python scripts/knowledge_hub_backfill.py embed [--textbook ID ...] [--limit N] [--dry-run]
    # 2) A3-style KU→chunk matching for KUs that have no matches yet
    python scripts/knowledge_hub_backfill.py match [--textbook ID ...] [--top-k 3] [--dry-run]

Both are insert/fill-only: `embed` only fills NULL embeddings, `match` only adds
rows for KUs that have none (never rewrites or deletes existing matches, and never
touches `verified`). Matching stays within the KU's own textbook, same as A3, and
uses the same embedding model as the stored chunk vectors (vectors of another
dimension are ignored). Precision caveat (A3, ~13% wrong matches): results are
inferred, verified=false, and go through the manual review gate
(export_ku_chunk_review.py / apply_ku_chunk_review.py).

GPU note (2026-10-11): run with a modest pace; the 8B embedding model on the
RTX 3080 coincided with a "GPU fallen off the bus" crash. --sleep adds a pause
between embedding calls.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(os.environ.get("MNEME_ROOT") or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


def _ku_text(name: str, description: Optional[str]) -> str:
    return f"{name}：{description}" if description else name


async def backfill_embeddings(
    db: AsyncSession,
    *,
    textbook_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    sleep_s: float = 0.0,
) -> dict:
    from oprim.embed_chunks import embed_text_with_model

    where = "tc.embedding IS NULL"
    params: dict = {}
    if textbook_ids:
        where += " AND tf.textbook_id = ANY(:tbs)"
        params["tbs"] = textbook_ids
    sql = (
        "SELECT tc.id, tc.content FROM textbook_chunks tc "
        f"JOIN textbook_files tf ON tf.id = tc.file_id WHERE {where} ORDER BY tc.id"
    )
    if limit:
        sql += " LIMIT :lim"
        params["lim"] = limit
    rows = (await db.execute(sa_text(sql), params)).fetchall()
    if dry_run:
        return {"pending": len(rows), "embedded": 0, "failed": 0}

    ok = failed = 0
    for r in rows:
        vec, model = await embed_text_with_model(r.content)
        if not vec:
            failed += 1
            if failed >= 5 and ok == 0:
                break  # embedder down — stop instead of grinding through everything
            continue
        await db.execute(
            sa_text(
                "UPDATE textbook_chunks SET embedding=:e, embedding_model=:m,"
                " embedded_at=:t WHERE id=:id AND embedding IS NULL"
            ),
            {"e": vec, "m": model, "t": datetime.now(timezone.utc), "id": r.id},
        )
        ok += 1
        if ok % 50 == 0:
            await db.commit()
        if sleep_s:
            await asyncio.sleep(sleep_s)
    await db.commit()
    return {"pending": len(rows), "embedded": ok, "failed": failed}


async def match_kus(
    db: AsyncSession,
    *,
    textbook_ids: list[str],
    top_k: int = 3,
    dry_run: bool = False,
    sleep_s: float = 0.0,
) -> dict:
    from oprim.embed_chunks import embed_text_with_model

    summary: dict[str, dict] = {}
    for tb in textbook_ids:
        chunks = (
            await db.execute(
                sa_text(
                    "SELECT tc.id, tc.embedding FROM textbook_chunks tc "
                    "JOIN textbook_files tf ON tf.id = tc.file_id "
                    "WHERE tf.textbook_id = :tb AND tc.embedding IS NOT NULL"
                ),
                {"tb": tb},
            )
        ).fetchall()
        kus = (
            await db.execute(
                sa_text(
                    "SELECT k.id, k.name, k.description FROM knowledge_units k "
                    "WHERE k.textbook_id = :tb AND NOT EXISTS "
                    "(SELECT 1 FROM ku_chunk_matches m WHERE m.ku_id = k.id) ORDER BY k.id"
                ),
                {"tb": tb},
            )
        ).fetchall()
        stat = {"chunks": len(chunks), "kus_pending": len(kus), "matched": 0, "failed": 0}
        summary[tb] = stat
        if dry_run or not chunks or not kus:
            continue

        by_dim: dict[int, tuple[list[str], np.ndarray]] = {}
        for dim in {len(c.embedding) for c in chunks}:
            same = [c for c in chunks if len(c.embedding) == dim]
            m = np.asarray([c.embedding for c in same], dtype=np.float32)
            n = np.linalg.norm(m, axis=1, keepdims=True)
            n[n == 0] = 1.0
            by_dim[dim] = ([c.id for c in same], m / n)

        for ku in kus:
            vec, model = await embed_text_with_model(_ku_text(ku.name, ku.description))
            if not vec or len(vec) not in by_dim:
                stat["failed"] += 1
                if stat["failed"] >= 5 and stat["matched"] == 0:
                    break
                continue
            ids, mat = by_dim[len(vec)]
            q = np.asarray(vec, dtype=np.float32)
            qn = float(np.linalg.norm(q)) or 1.0
            scores = mat @ (q / qn)
            order = np.argsort(-scores, kind="stable")[:top_k]
            for rank, i in enumerate(order, 1):
                await db.execute(
                    sa_text(
                        "INSERT INTO ku_chunk_matches (id, ku_id, chunk_id, rank, score,"
                        " method, created_at, verified) VALUES (:id, :ku, :ch, :rk, :sc,"
                        " :me, now(), false)"
                    ),
                    {
                        "id": f"kcm_{uuid.uuid4().hex[:16]}",
                        "ku": ku.id,
                        "ch": ids[int(i)],
                        "rk": rank,
                        "sc": float(scores[int(i)]),
                        "me": f"embedding_cosine_{model}",
                    },
                )
            stat["matched"] += 1
            if stat["matched"] % 25 == 0:
                await db.commit()
            if sleep_s:
                await asyncio.sleep(sleep_s)
        await db.commit()
    return summary


async def _textbooks_for(db: AsyncSession, subjects: Optional[list[str]]) -> list[str]:
    sql = (
        "SELECT DISTINCT tf.textbook_id FROM textbook_files tf "
        "JOIN textbooks t ON t.id = tf.textbook_id WHERE tf.index_status = 'ready'"
    )
    params: dict = {}
    if subjects:
        sql += " AND t.subject = ANY(:s)"
        params["s"] = subjects
    return [r[0] for r in (await db.execute(sa_text(sql + " ORDER BY 1"), params))]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["embed", "match"])
    ap.add_argument("--textbook", action="append")
    ap.add_argument("--subjects", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from obase.db import SessionLocal

    async with SessionLocal() as db:
        tbs = args.textbook or (
            await _textbooks_for(db, args.subjects) if args.subjects or args.cmd == "match" else None
        )
        if args.cmd == "embed":
            res = await backfill_embeddings(
                db, textbook_ids=tbs, limit=args.limit, dry_run=args.dry_run, sleep_s=args.sleep
            )
            print(res, flush=True)
        else:
            res2 = await match_kus(
                db, textbook_ids=tbs or [], top_k=args.top_k, dry_run=args.dry_run, sleep_s=args.sleep
            )
            for tb, st in res2.items():
                print(tb, st, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

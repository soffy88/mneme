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

CPU backend (2026-10-11, after the GPU died): `--backend cpu` (default when
MNEME_EMBED_BACKEND=cpu) uses the CPU embedding sidecar (default bge-small-zh-v1.5) (services/text_embedder,
compose service `embedder`). `embed` then inserts into textbook_chunk_embeddings
(one row per chunk+model, ON CONFLICT DO NOTHING — the old 4096-dim
textbook_chunks.embedding column is never touched), and `match` scores KUs
against those vectors and records method=embedding_cosine_bge-small-zh-v1.5. Run it inside
mneme-api-1 so it can reach the sidecar, niced, e.g.:

    docker exec -d mneme-api-1 sh -c 'cd /app && nice -n 15 python \
        scripts/knowledge_hub_backfill.py embed --backend cpu --batch 16 --sleep 0.2 \
        > /tmp/kh_embed.log 2>&1'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
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


async def backfill_embeddings_cpu(
    db: AsyncSession,
    *,
    textbook_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    sleep_s: float = 0.0,
    batch: int = 16,
) -> dict:
    """CPU 侧车向量 → textbook_chunk_embeddings（insert-only，旧列不动）。"""
    from services.text_embedder import cpu_embed_model, embed_texts_cpu

    model = cpu_embed_model()
    where = (
        "NOT EXISTS (SELECT 1 FROM textbook_chunk_embeddings e"
        " WHERE e.chunk_id = tc.id AND e.model = :model)"
    )
    params: dict = {"model": model}
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
        return {"model": model, "pending": len(rows), "embedded": 0, "failed": 0}

    ok = failed = streak = 0
    t0 = time.monotonic()
    for s in range(0, len(rows), batch):
        part = rows[s : s + batch]
        vecs = await embed_texts_cpu([r.content for r in part], timeout=120)
        if not vecs:
            failed += len(part)
            streak += 1
            if streak >= 3:
                break  # 侧车宕了：停，不硬磨
            await asyncio.sleep(5)
            continue
        streak = 0
        for r, v in zip(part, vecs):
            await db.execute(
                sa_text(
                    "INSERT INTO textbook_chunk_embeddings (chunk_id, model, dim, embedding,"
                    " embedded_at) VALUES (:id, :m, :d, :e, now())"
                    " ON CONFLICT (chunk_id, model) DO NOTHING"
                ),
                {"id": r.id, "m": model, "d": len(v), "e": v},
            )
        await db.commit()
        ok += len(part)
        if (s // batch) % 20 == 0:
            el = time.monotonic() - t0
            print(f"embedded {ok}/{len(rows)} in {el:.0f}s ({ok / max(el, 1e-9):.1f}/s)", flush=True)
        if sleep_s:
            await asyncio.sleep(sleep_s)
    return {
        "model": model,
        "pending": len(rows),
        "embedded": ok,
        "failed": failed,
        "seconds": round(time.monotonic() - t0, 1),
    }


async def match_kus_cpu(
    db: AsyncSession,
    *,
    textbook_ids: list[str],
    top_k: int = 3,
    dry_run: bool = False,
    sleep_s: float = 0.0,
    batch: int = 16,
) -> dict:
    """A3 式 KU→chunk 挂接（CPU 侧车向量）：只给还没有任何挂接的 KU 插入，
    verified=false，method=embedding_cosine_<model>；同教材内匹配。"""
    from services.text_embedder import cpu_embed_model, embed_texts_cpu, match_method

    model = cpu_embed_model()
    method = match_method(model)
    summary: dict[str, dict] = {}
    for tb in textbook_ids:
        chunks = (
            await db.execute(
                sa_text(
                    "SELECT tc.id, e.embedding FROM textbook_chunk_embeddings e "
                    "JOIN textbook_chunks tc ON tc.id = e.chunk_id "
                    "JOIN textbook_files tf ON tf.id = tc.file_id "
                    "WHERE tf.textbook_id = :tb AND e.model = :m"
                ),
                {"tb": tb, "m": model},
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
        ids = [c.id for c in chunks]
        mat = np.asarray([c.embedding for c in chunks], dtype=np.float32)
        n = np.linalg.norm(mat, axis=1, keepdims=True)
        n[n == 0] = 1.0
        mat = mat / n
        for s in range(0, len(kus), batch):
            part = kus[s : s + batch]
            vecs = await embed_texts_cpu(
                [_ku_text(k.name, k.description) for k in part], timeout=120, input_type="query"
            )
            if not vecs:
                stat["failed"] += len(part)
                if stat["matched"] == 0 and stat["failed"] >= 3 * batch:
                    break
                continue
            for ku, vec in zip(part, vecs):
                if len(vec) != mat.shape[1]:
                    stat["failed"] += 1
                    continue
                q = np.asarray(vec, dtype=np.float32)
                q = q / (float(np.linalg.norm(q)) or 1.0)
                scores = mat @ q
                order = np.argsort(-scores, kind="stable")[:top_k]
                for rank, i in enumerate(order, 1):
                    await db.execute(
                        sa_text(
                            "INSERT INTO ku_chunk_matches (id, ku_id, chunk_id, rank, score,"
                            " method, created_at, verified) VALUES (:id, :ku, :ch, :rk, :sc,"
                            " :me, now(), false) ON CONFLICT DO NOTHING"
                        ),
                        {
                            "id": f"kcm_{uuid.uuid4().hex[:16]}",
                            "ku": ku.id,
                            "ch": ids[int(i)],
                            "rk": rank,
                            "sc": float(scores[int(i)]),
                            "me": method,
                        },
                    )
                stat["matched"] += 1
            await db.commit()
            if sleep_s:
                await asyncio.sleep(sleep_s)
        print(tb, stat, flush=True)
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
    ap.add_argument("--backend", choices=["legacy", "cpu"])
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    from services.text_embedder import embed_backend

    backend = args.backend or ("cpu" if embed_backend() == "cpu" else "legacy")

    from obase.db import SessionLocal

    async with SessionLocal() as db:
        tbs = args.textbook or (
            await _textbooks_for(db, args.subjects) if args.subjects or args.cmd == "match" else None
        )
        if backend == "cpu" and args.cmd == "embed":
            print(
                await backfill_embeddings_cpu(
                    db, textbook_ids=tbs, limit=args.limit, dry_run=args.dry_run,
                    sleep_s=args.sleep, batch=args.batch,
                ),
                flush=True,
            )
        elif backend == "cpu":
            res3 = await match_kus_cpu(
                db, textbook_ids=tbs or [], top_k=args.top_k, dry_run=args.dry_run,
                sleep_s=args.sleep, batch=args.batch,
            )
            tot = {k: sum(v[k] for v in res3.values()) for k in ("kus_pending", "matched", "failed")}
            print("TOTAL", tot, flush=True)
        elif args.cmd == "embed":
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

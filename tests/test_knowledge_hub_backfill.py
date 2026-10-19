"""scripts/knowledge_hub_backfill.py：embed 回填 + KU→chunk 挂接（只增不改）。假 embedder。"""

from __future__ import annotations

import importlib.util
import importlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, TextbookFile

_SPEC = importlib.util.spec_from_file_location(
    "knowledge_hub_backfill",
    Path(__file__).parent.parent / "scripts" / "knowledge_hub_backfill.py",
)
assert _SPEC and _SPEC.loader
khb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(khb)

_VECS = {"A": [1.0, 0.0, 0.0], "B": [0.0, 1.0, 0.0], "C": [0.0, 0.0, 1.0]}


async def _fake_embed(text):
    for key, vec in _VECS.items():
        if key in text:
            return vec, "fake-embed"
    return None, None


@pytest.fixture
async def seeded():
    tb = f"tb-khb-{uuid.uuid4().hex[:8]}"
    fid = f"{tb}-f"
    chunk_ids = [f"{tb}-ch-{k}" for k in "ABC"]
    ku_ids = [f"{tb}-ku-{k}" for k in "AB"]
    async with SessionLocal() as db:
        db.add(Textbook(id=tb, subject="physics", grade="G8", edition="t", book_name="回填测试"))
        await db.flush()
        db.add(KnowledgeCluster(id=f"{tb}-c", textbook_id=tb, name="c", display_order=1))
        await db.flush()
        for kid, k in zip(ku_ids, "AB"):
            db.add(
                KnowledgeUnit(
                    id=kid, textbook_id=tb, cluster_id=f"{tb}-c", name=f"知识点{k}", description=None
                )
            )
        db.add(
            TextbookFile(
                id=fid, textbook_id=tb, filename="t.pdf", file_type="pdf", storage_path="/tmp/t.pdf"
            )
        )
        await db.flush()
        for i, (cid, k) in enumerate(zip(chunk_ids, "ABC")):
            await db.execute(
                sa_text(
                    "INSERT INTO textbook_chunks (id, file_id, page_number, chunk_index,"
                    " content, content_length, created_at) VALUES (:id, :f, 1, :i, :c, 3, now())"
                ),
                {"id": cid, "f": fid, "i": i, "c": f"内容{k}"},
            )
        await db.commit()
    yield tb, chunk_ids, ku_ids
    async with SessionLocal() as db:
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb))
        await db.execute(sa_text("DELETE FROM textbook_files WHERE id=:f"), {"f": fid})
        await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb))
        await db.execute(delete(Textbook).where(Textbook.id == tb))
        await db.commit()


@pytest.mark.asyncio
async def test_backfill_then_match_is_fill_only_and_idempotent(monkeypatch, seeded):
    tb, chunk_ids, ku_ids = seeded
    embed_chunks_module = importlib.import_module("oprim.embed_chunks")
    monkeypatch.setattr(embed_chunks_module, "embed_text_with_model", _fake_embed)

    async with SessionLocal() as db:
        dry = await khb.backfill_embeddings(db, textbook_ids=[tb], dry_run=True)
        assert dry == {"pending": 3, "embedded": 0, "failed": 0}
        res = await khb.backfill_embeddings(db, textbook_ids=[tb])
        assert res == {"pending": 3, "embedded": 3, "failed": 0}
        again = await khb.backfill_embeddings(db, textbook_ids=[tb])
        assert again["pending"] == 0

        summary = await khb.match_kus(db, textbook_ids=[tb], top_k=2)
        assert summary[tb]["matched"] == 2
        rows = (
            await db.execute(
                sa_text(
                    "SELECT ku_id, chunk_id, rank, score, method, verified FROM ku_chunk_matches"
                    " WHERE ku_id = ANY(:k) ORDER BY ku_id, rank"
                ),
                {"k": ku_ids},
            )
        ).fetchall()
        assert len(rows) == 4
        top = {r.ku_id: r.chunk_id for r in rows if r.rank == 1}
        assert top == {ku_ids[0]: chunk_ids[0], ku_ids[1]: chunk_ids[1]}
        assert all(r.method == "embedding_cosine_fake-embed" and r.verified is False for r in rows)
        assert next(r.score for r in rows if r.rank == 1) == pytest.approx(1.0)

        rerun = await khb.match_kus(db, textbook_ids=[tb], top_k=2)
        assert rerun[tb]["kus_pending"] == 0 and rerun[tb]["matched"] == 0
        n = (
            await db.execute(
                sa_text("SELECT count(*) FROM ku_chunk_matches WHERE ku_id = ANY(:k)"),
                {"k": ku_ids},
            )
        ).scalar()
        assert n == 4


@pytest.mark.asyncio
async def test_backfill_stops_early_when_embedder_down(monkeypatch, seeded):
    tb, _, _ = seeded

    async def down(text):
        del text
        return None, None

    monkeypatch.setattr("oprim.embed_chunks.embed_text_with_model", down)
    async with SessionLocal() as db:
        res = await khb.backfill_embeddings(db, textbook_ids=[tb])
    assert res["embedded"] == 0 and res["failed"] == 3

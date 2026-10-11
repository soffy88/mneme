"""CPU embedding 侧车（bge-m3）接入：后端配置、兜底、按模型分存的向量、按模型标定的阈值。

不起真侧车：services.text_embedder.embed_texts_cpu 用假实现替换，或把 URL 指向
一个不监听的端口验证"侧车宕 → 词面兜底"。
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from services import knowledge_hub_search as khs
from services import text_embedder as te
from services.knowledge_hub_search import min_score_for, search_knowledge_base
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, TextbookFile

_SPEC = importlib.util.spec_from_file_location(
    "knowledge_hub_backfill_cpu",
    Path(__file__).parent.parent / "scripts" / "knowledge_hub_backfill.py",
)
assert _SPEC and _SPEC.loader
khb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(khb)

_VECS = {"甲": [1.0, 0.0, 0.0], "乙": [0.0, 1.0, 0.0], "丙": [0.0, 0.0, 1.0]}


def _vec_for(text: str) -> list[float]:
    for k, v in _VECS.items():
        if k in text:
            return v
    return [0.5, 0.5, 0.0]


async def _fake_cpu(texts, *, timeout=30.0):
    del timeout
    return [_vec_for(t) for t in texts]


async def _down_cpu(texts, *, timeout=30.0):
    del texts, timeout
    return None


@pytest.fixture(autouse=True)
def _cpu_env(monkeypatch):
    monkeypatch.setenv("MNEME_EMBED_BACKEND", "cpu")
    monkeypatch.setenv("MNEME_EMBED_MODEL", "bge-m3")
    khs._EMBED_STATE["down_until"] = 0.0
    khs._EMB_CACHE.clear()
    yield
    khs._EMBED_STATE["down_until"] = 0.0
    khs._EMB_CACHE.clear()


@pytest.fixture
async def seeded():
    tb = f"tb-kcpu-{uuid.uuid4().hex[:8]}"
    fid = f"{tb}-f"
    chunk_ids = [f"{tb}-ch-{k}" for k in ("甲", "乙", "丙")]
    async with SessionLocal() as db:
        db.add(Textbook(id=tb, subject="physics", grade="G8", edition="t", book_name="CPU检索测试"))
        await db.flush()
        db.add(KnowledgeCluster(id=f"{tb}-c", textbook_id=tb, name="c", display_order=1))
        await db.flush()
        for k in ("甲", "乙"):
            db.add(
                KnowledgeUnit(
                    id=f"{tb}-ku-{k}", textbook_id=tb, cluster_id=f"{tb}-c",
                    name=f"知识点{k}", description=None,
                )
            )
        db.add(
            TextbookFile(
                id=fid, textbook_id=tb, filename="t.pdf", file_type="pdf", storage_path="/tmp/t.pdf"
            )
        )
        await db.flush()
        for i, (cid, k) in enumerate(zip(chunk_ids, ("甲", "乙", "丙"))):
            await db.execute(
                sa_text(
                    "INSERT INTO textbook_chunks (id, file_id, page_number, chunk_index,"
                    " content, content_length, created_at) VALUES (:id, :f, :p, :i, :c, 6, now())"
                ),
                {"id": cid, "f": fid, "p": i + 1, "i": i, "c": f"CPU检索内容{k}"},
            )
        await db.commit()
    yield tb, chunk_ids
    async with SessionLocal() as db:
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb))
        await db.execute(sa_text("DELETE FROM textbook_files WHERE id=:f"), {"f": fid})
        await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb))
        await db.execute(delete(Textbook).where(Textbook.id == tb))
        await db.commit()


# ── 配置 ────────────────────────────────────────────────────────────────────


def test_backend_config(monkeypatch):
    monkeypatch.delenv("MNEME_EMBED_BACKEND", raising=False)
    assert te.embed_backend() == "legacy"  # 未配置：旧行为
    for v in ("cpu", "legacy", "off", " CPU "):
        monkeypatch.setenv("MNEME_EMBED_BACKEND", v)
        assert te.embed_backend() == v.strip().lower()
    monkeypatch.setenv("MNEME_EMBED_BACKEND", "gpu")
    assert te.embed_backend() == "legacy"
    monkeypatch.delenv("MNEME_EMBED_URL", raising=False)
    assert te.cpu_embed_url() == "http://embedder:8080/v1"
    monkeypatch.setenv("MNEME_EMBED_URL", "http://x:1/v1/")
    assert te.cpu_embed_url() == "http://x:1/v1"
    assert te.match_method("bge-m3") == "embedding_cosine_bge-m3"


def test_min_score_profiles_and_env_override(monkeypatch):
    assert min_score_for("book") == 0.60  # 旧模型 R1 不变
    assert min_score_for("chat") == 0.58
    assert min_score_for("chat", "legacy") == 0.58
    bge = khs.MIN_SCORE_PROFILES["bge-m3"]
    assert min_score_for("book", "bge-m3") == bge["book"]
    assert min_score_for("chat", "bge-m3") == bge["chat"]
    assert bge["book"] >= bge["chat"]  # Book 宁缺毋滥
    monkeypatch.setenv("KNOWLEDGE_HUB_MIN_SCORE_BGE_M3_CHAT", "0.7")
    assert min_score_for("chat", "bge-m3") == 0.7
    monkeypatch.setenv("KNOWLEDGE_HUB_MIN_SCORE_BGE_M3_CHAT", "abc")
    assert min_score_for("chat", "bge-m3") == bge["chat"]
    assert khs._model_of_method("embedding_cosine_bge-m3") == "bge-m3"
    assert khs._model_of_method("embedding_cosine_qwen3-embedding") is None
    assert khs._model_of_method(None) is None


@pytest.mark.asyncio
async def test_embed_texts_cpu_parses_openai_shape(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]},
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        te.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    assert await te.embed_texts_cpu(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert await te.embed_texts_cpu([]) == []


@pytest.mark.asyncio
async def test_embed_texts_cpu_bad_status_or_shape_is_none(monkeypatch):
    responses = iter(
        [httpx.Response(500, text="boom"), httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})]
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        te.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: next(responses)), **kw),
    )
    assert await te.embed_texts_cpu(["a"]) is None
    assert await te.embed_texts_cpu(["a", "b"]) is None  # 条数不符


@pytest.mark.asyncio
async def test_sidecar_down_falls_back_to_lexical(monkeypatch, seeded):
    monkeypatch.setenv("MNEME_EMBED_URL", "http://127.0.0.1:9/v1")  # 无人监听
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="CPU检索内容甲", top_k=3)
        # Book 场景（purpose=book）宁缺毋滥：不走词面
        res_book = await search_knowledge_base(db, query="CPU检索内容甲", top_k=3, purpose="book")
    assert res.get("retrieval") == "lexical"
    assert res["results"]
    assert res_book["results"] == []


@pytest.mark.asyncio
async def test_backend_off_skips_embedding(monkeypatch, seeded):
    monkeypatch.setenv("MNEME_EMBED_BACKEND", "off")
    monkeypatch.setattr(te, "embed_texts_cpu", _fake_cpu)
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="CPU检索内容乙", top_k=3)
    assert res.get("retrieval") == "lexical"


# ── 回填 + 语义检索（新表） ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cpu_backfill_is_insert_only_and_feeds_semantic_search(monkeypatch, seeded):
    tb, chunk_ids = seeded
    monkeypatch.setattr(te, "embed_texts_cpu", _fake_cpu)
    async with SessionLocal() as db:
        old = (
            await db.execute(sa_text("SELECT count(*) FROM textbook_chunks WHERE id = ANY(:i) AND embedding IS NOT NULL"), {"i": chunk_ids})
        ).scalar()
        r1 = await khb.backfill_embeddings_cpu(db, textbook_ids=[tb], batch=2)
        r2 = await khb.backfill_embeddings_cpu(db, textbook_ids=[tb], batch=2)
        assert (r1["embedded"], r1["failed"]) == (3, 0)
        assert r2["pending"] == 0  # 幂等：已有的不重算
        rows = (
            await db.execute(
                sa_text("SELECT chunk_id, model, dim FROM textbook_chunk_embeddings WHERE chunk_id = ANY(:i)"),
                {"i": chunk_ids},
            )
        ).fetchall()
        assert {(r.model, r.dim) for r in rows} == {("bge-m3", 3)} and len(rows) == 3
        # 旧列不动
        assert old == (
            await db.execute(sa_text("SELECT count(*) FROM textbook_chunks WHERE id = ANY(:i) AND embedding IS NOT NULL"), {"i": chunk_ids})
        ).scalar()

        res = await search_knowledge_base(db, query="问乙", top_k=3, min_score=0.5)
    assert "retrieval" not in res
    assert res["embedding_model"] == "bge-m3"
    assert [r["chunk_id"] for r in res["results"]][:1] == [chunk_ids[1]]
    assert res["results"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_cpu_semantic_ignores_vectors_of_other_models(monkeypatch, seeded):
    tb, chunk_ids = seeded
    monkeypatch.setattr(te, "embed_texts_cpu", _fake_cpu)
    async with SessionLocal() as db:
        await db.execute(
            sa_text(
                "INSERT INTO textbook_chunk_embeddings (chunk_id, model, dim, embedding)"
                " VALUES (:c, 'other-model', 3, :e)"
            ),
            {"c": chunk_ids[0], "e": [1.0, 0.0, 0.0]},
        )
        await db.commit()
        res = await search_knowledge_base(db, query="问甲", top_k=3)
    # 库里没有 bge-m3 向量（只有 other-model 的）→ 语义不可用 → 词面兜底
    assert res.get("retrieval") == "lexical"


@pytest.mark.asyncio
async def test_cpu_purpose_threshold_uses_bge_profile(monkeypatch, seeded):
    tb, chunk_ids = seeded
    monkeypatch.setattr(te, "embed_texts_cpu", _fake_cpu)
    monkeypatch.setitem(khs.MIN_SCORE_PROFILES, "bge-m3", {"book": 0.9, "chat": 0.6})
    async with SessionLocal() as db:
        await khb.backfill_embeddings_cpu(db, textbook_ids=[tb], batch=8)
        # query 向量 [0.5,0.5,0] 与 甲/乙 cosine≈0.707，与 丙 = 0
        chat = await search_knowledge_base(db, query="无关", top_k=3, purpose="chat")
        book = await search_knowledge_base(db, query="无关", top_k=3, purpose="book")
    assert len(chat["results"]) == 2
    assert book["results"] == []


@pytest.mark.asyncio
async def test_cpu_match_inserts_unverified_rows_and_kc_threshold_per_method(monkeypatch, seeded):
    tb, chunk_ids = seeded
    monkeypatch.setattr(te, "embed_texts_cpu", _fake_cpu)
    async with SessionLocal() as db:
        await khb.backfill_embeddings_cpu(db, textbook_ids=[tb], batch=8)
        s1 = await khb.match_kus_cpu(db, textbook_ids=[tb], top_k=2)
        s2 = await khb.match_kus_cpu(db, textbook_ids=[tb], top_k=2)
        assert s1[tb]["matched"] == 2 and s2[tb]["kus_pending"] == 0
        rows = (
            await db.execute(
                sa_text(
                    "SELECT ku_id, chunk_id, rank, score, method, verified FROM ku_chunk_matches"
                    " WHERE ku_id LIKE :p ORDER BY ku_id, rank"
                ),
                {"p": f"{tb}-ku-%"},
            )
        ).fetchall()
        assert len(rows) == 4
        assert all(r.method == "embedding_cosine_bge-m3" and r.verified is False for r in rows)
        top = {r.ku_id: r.chunk_id for r in rows if r.rank == 1}
        assert top == {f"{tb}-ku-甲": chunk_ids[0], f"{tb}-ku-乙": chunk_ids[1]}

        monkeypatch.setitem(khs.MIN_SCORE_PROFILES, "bge-m3", {"book": 0.5, "chat": 0.4})
        res = await search_knowledge_base(db, kc_id=f"{tb}-ku-甲", top_k=3, purpose="book")
        assert [r["chunk_id"] for r in res["results"]] == [chunk_ids[0]]  # rank2 cos=0 被滤
        monkeypatch.setitem(khs.MIN_SCORE_PROFILES, "bge-m3", {"book": 1.01, "chat": 0.4})
        res = await search_knowledge_base(db, kc_id=f"{tb}-ku-甲", top_k=3, purpose="book")
        assert res["results"] == []

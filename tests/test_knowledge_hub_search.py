"""W3 A5 验收：SearchTextbookKnowledge（Mneme 自建 Knowledge Hub）返回带出处结果。

覆盖 kc_id 路径（走 A3 预计算的 ku_chunk_matches）和 free_text 路径（实时 embed +
全库 cosine）。断言：返回全部候选（非只 rank-1）、每条带 score、
provenance 硬编码为 "inferred"（不伪装权威）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from services.knowledge_hub_search import citation_state, search_knowledge_base
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, TextbookFile


@pytest.fixture(autouse=True)
async def _seed_ku_chunk_matches():
    """自包含 A3 挂接数据夹具：kc_id 路径测试需要 ku_chunk_matches 非空，但共享
    测试库没跑过 A3 批量挂接（0 行）。这里种一条专用链路：
    textbook → cluster → KU → file → 3 chunks → 3 matches（rank 1/2/3，分数递减
    且都 <0.999，满足 top3/min_score 两个断言）。测完即清，不污染共享库。"""
    import uuid as _uuid

    from sqlalchemy import delete

    tb_id = f"tb-khs-{_uuid.uuid4().hex[:8]}"
    c_id = f"{tb_id}-c1"
    ku_id = f"{tb_id}-ku-1"
    file_id = f"{tb_id}-f1"
    chunk_ids = [f"{tb_id}-ch-{i}" for i in range(3)]
    match_ids = [f"{tb_id}-m-{i}" for i in range(3)]
    scores = [0.9, 0.8, 0.7]  # 递减，且都 < 0.999

    async with SessionLocal() as db:
        db.add(
            Textbook(
                id=tb_id,
                subject="math",
                grade="G1",
                edition="测试版",
                book_name="检索测试教材",
            )
        )
        await db.flush()
        db.add(
            KnowledgeCluster(
                id=c_id, textbook_id=tb_id, name="检索测试章节", display_order=1
            )
        )
        await db.flush()
        db.add(
            KnowledgeUnit(
                id=ku_id,
                textbook_id=tb_id,
                cluster_id=c_id,
                name="检索测试知识点",
                description="检索测试",
            )
        )
        await db.flush()
        db.add(
            TextbookFile(
                id=file_id,
                textbook_id=tb_id,
                filename="search_test.pdf",
                file_type="pdf",
                storage_path="/tmp/search_test.pdf",
            )
        )
        await db.flush()
        # chunks + matches 无 ORM 模型，走原生 SQL
        for i, (ch_id, m_id, score) in enumerate(
            zip(chunk_ids, match_ids, scores)
        ):
            await db.execute(
                sa_text(
                    """
                INSERT INTO textbook_chunks
                    (id, file_id, page_number, chunk_index, content, content_length,
                     char_start, char_end, created_at)
                VALUES (:id, :fid, :pg, :ci, :content, :clen, :cs, :ce, now())
                """
                ),
                {
                    "id": ch_id,
                    "fid": file_id,
                    "pg": i + 1,
                    "ci": i,
                    "content": f"检索测试内容 {i}",
                    "clen": 10,
                    "cs": i * 10,
                    "ce": i * 10 + 10,
                },
            )
            await db.execute(
                sa_text(
                    """
                INSERT INTO ku_chunk_matches
                    (id, ku_id, chunk_id, rank, score, method, created_at, verified)
                VALUES (:id, :ku, :ch, :rank, :score, 'a3_test', now(), false)
                """
                ),
                {
                    "id": m_id,
                    "ku": ku_id,
                    "ch": ch_id,
                    "rank": i + 1,
                    "score": score,
                },
            )
        await db.commit()

    yield ku_id

    async with SessionLocal() as db:
        # 级联：matches/chunks 随 KU/file 删除；再清教材三件套
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == ku_id))
        await db.execute(
            sa_text("DELETE FROM textbook_files WHERE id=:fid"), {"fid": file_id}
        )
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.id == c_id)
        )
        await db.execute(delete(Textbook).where(Textbook.id == tb_id))
        await db.commit()


@pytest.mark.asyncio
async def test_search_by_kc_id_returns_top3_with_provenance_and_scores():
    async with SessionLocal() as db:
        # 取一个真实已挂接的 KU（A3 批量跑过，ku_chunk_matches 应有数据）
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        assert row is not None, "ku_chunk_matches 为空——先跑 A3 批量挂接"
        kc_id = row[0]

        result = await search_knowledge_base(db, kc_id=kc_id, top_k=3)

    assert result["query_type"] == "kc_id"
    assert len(result["results"]) == 3
    ranks = [r["rank"] for r in result["results"]]
    assert ranks == [1, 2, 3]
    scores = [r["score"] for r in result["results"]]
    assert scores == sorted(scores, reverse=True)  # rank 1 分数最高
    for r in result["results"]:
        assert r["provenance"] == "inferred"
        assert isinstance(r["score"], float)
        assert r["chunk_id"]
        assert r["pdf_id"]
        assert "textbook_meta" in r


@pytest.mark.asyncio
async def test_search_by_free_text_returns_scored_inferred_results():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, query="等差数列的通项公式", top_k=3)

    assert result["query_type"] == "free_text"
    assert len(result["results"]) <= 3
    if result["results"]:
        for r in result["results"]:
            assert r["provenance"] == "inferred"
            assert isinstance(r["score"], float)
        scores = [r["score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_with_neither_kc_id_nor_query_returns_empty_not_error():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db)

    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_by_unknown_kc_id_returns_empty_not_error():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, kc_id="does-not-exist-xyz")

    assert result["query_type"] == "kc_id"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_min_score_filters_out_low_confidence_matches():
    """Part B spec R1：挂接分 < 阈值不返回（垃圾兜底，见 knowledge_hub_search.py
    模块顶部——不宣称这保证正确，只是滤掉最明显的）。
    """
    async with SessionLocal() as db:
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        kc_id = row[0]

        unfiltered = await search_knowledge_base(
            db, kc_id=kc_id, top_k=3, min_score=0.0
        )
        filtered = await search_knowledge_base(
            db, kc_id=kc_id, top_k=3, min_score=0.999
        )

    assert len(unfiltered["results"]) == 3
    assert len(filtered["results"]) == 0  # 0.999 高于任何真实 cosine 分数


@pytest.mark.asyncio
async def test_every_result_carries_verified_field_and_citation_state():
    """R3/R4：每条结果必须带 verified 字段，citation_state() 据此二态映射，
    不分高低分——见 knowledge_hub_search.py 顶部关于 0.732 也可能是错的说明。
    """
    async with SessionLocal() as db:
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        result = await search_knowledge_base(db, kc_id=row[0], top_k=3)

    for r in result["results"]:
        assert "verified" in r
        assert isinstance(r["verified"], bool)
        assert citation_state(r) in ("verified", "inferred_unverified")
        assert citation_state(r) == (
            "verified" if r["verified"] else "inferred_unverified"
        )


@pytest.mark.asyncio
async def test_free_text_results_are_always_unverified():
    """free_text 路径不经 KU 挂接人工校订机制，恒为 unverified。"""
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, query="等差数列的通项公式", top_k=3)

    for r in result["results"]:
        assert r["verified"] is False
        assert citation_state(r) == "inferred_unverified"


@pytest.mark.asyncio
async def test_free_text_falls_back_to_lexical_when_embedding_unavailable(
    monkeypatch,
):
    """embed 服务不可用（2026-10 生产实况：Ollama 模型缺失）→ 词面兜底仍返回带出处结果。"""

    async def no_embed(text):
        del text
        return None

    monkeypatch.setattr("oprim.embed_chunks.embed_text", no_embed)
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, query="检索测试内容", top_k=3)

    assert result["query_type"] == "free_text"
    assert result["retrieval"] == "lexical"
    assert 1 <= len(result["results"]) <= 3
    for r in result["results"]:
        assert "检索测试内容" in r["content"]
        assert r["provenance"] == "inferred"
        assert r["verified"] is False
        assert 0.0 < r["score"] <= 1.0
    assert [r["rank"] for r in result["results"]] == list(
        range(1, len(result["results"]) + 1)
    )


@pytest.mark.asyncio
async def test_lexical_fallback_uses_cjk_ngrams_for_longer_phrases(monkeypatch):
    async def no_embed(text):
        del text
        return None

    monkeypatch.setattr("oprim.embed_chunks.embed_text", no_embed)
    async with SessionLocal() as db:
        # 整句在库里不存在，但其三元组过半命中种子 chunk "检索测试内容 N"
        result = await search_knowledge_base(db, query="检索测试内容的意思", top_k=3)

    assert result.get("retrieval") == "lexical"
    assert result["results"], "二元组兜底应召回种子 chunk"


@pytest.mark.asyncio
async def test_lexical_fallback_disabled_when_min_score_set(monkeypatch):
    """Book Engine 传 R1 阈值时不走词面兜底（词面分不是 cosine，量纲不同）。"""

    async def no_embed(text):
        del text
        return None

    monkeypatch.setattr("oprim.embed_chunks.embed_text", no_embed)
    async with SessionLocal() as db:
        result = await search_knowledge_base(
            db, query="检索测试内容", top_k=3, min_score=0.6
        )
    assert result["results"] == []
    assert "retrieval" not in result


def test_lexical_helpers():
    from services.knowledge_hub_search import (
        _clean_ratio,
        _cjk_ngrams,
        _is_toc_chunk,
        _lexical_score,
        _lexical_terms,
    )

    assert _lexical_terms("勾股定理， 逆定理 a") == ["勾股定理", "逆定理"]
    assert _cjk_ngrams("一元二次", 2) == ["一元", "元二", "二次"]
    assert _cjk_ngrams("光合作用", 3) == ["光合作", "合作用"]
    assert _clean_ratio("第二十章 勾股定理 直角三角形，a²+b²=c²。") == 1.0
    assert _clean_ratio("ᑓ ᄼ5 ᄼ ᄼᑓ ߦ၏ ڏឭ") < 0.6
    assert _is_toc_chunk("目 录 第十九章 二次根式 １ 第二十章 勾股定理")
    assert not _is_toc_chunk("第二十章 勾股定理 在西方，人们称勾股定理为毕达哥拉斯定理")
    assert _lexical_score("勾股定理勾股定理", ["勾股定理"]) == round(0.8 + 0.2 * 2 / 5, 4)
    assert _lexical_score("无关", ["勾股定理"]) == 0.0


@pytest.mark.asyncio
async def test_free_text_semantic_uses_cached_matrix_and_refreshes_on_change(
    monkeypatch, _seed_ku_chunk_matches
):
    """语义路径：cosine 排序 + min_score 过滤；chunk 向量变化后缓存指纹失效重载。"""
    ku_id = _seed_ku_chunk_matches
    tb_id = ku_id.rsplit("-ku-", 1)[0]
    ch = [f"{tb_id}-ch-{i}" for i in range(3)]

    async def fake_embed(text):
        del text
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr("oprim.embed_chunks.embed_text", fake_embed)

    async def set_emb(vectors):
        async with SessionLocal() as db:
            for cid, vec in zip(ch, vectors):
                await db.execute(
                    sa_text(
                        "UPDATE textbook_chunks SET embedding=:e, embedded_at=now()"
                        " WHERE id=:id"
                    ),
                    {"e": vec, "id": cid},
                )
            await db.commit()

    await set_emb([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]])
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="x", top_k=3, min_score=0.5)
    assert "retrieval" not in res
    assert [r["chunk_id"] for r in res["results"]] == [ch[0], ch[2]]
    assert res["results"][0]["score"] == 1.0
    assert res["results"][1]["score"] == round(2**-0.5, 4)
    assert [r["rank"] for r in res["results"]] == [1, 2]

    await set_emb([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="x", top_k=3, min_score=0.5)
    assert [r["chunk_id"] for r in res["results"]] == [ch[1]]


@pytest.mark.asyncio
async def test_free_text_dimension_mismatch_falls_back_to_lexical(
    monkeypatch, _seed_ku_chunk_matches
):
    ku_id = _seed_ku_chunk_matches
    tb_id = ku_id.rsplit("-ku-", 1)[0]

    async def fake_embed(text):
        del text
        return [1.0, 0.0]  # 2 维 vs 库内 3 维 → 模型不一致

    monkeypatch.setattr("oprim.embed_chunks.embed_text", fake_embed)
    async with SessionLocal() as db:
        await db.execute(
            sa_text("UPDATE textbook_chunks SET embedding=:e WHERE id=:id"),
            {"e": [1.0, 0.0, 0.0], "id": f"{tb_id}-ch-0"},
        )
        await db.commit()
        res = await search_knowledge_base(db, query="检索测试内容", top_k=3)
    assert res.get("retrieval") == "lexical"
    assert res["results"]


@pytest.fixture(autouse=True)
def _legacy_embed_backend(monkeypatch):
    """本文件覆盖旧 oprim.embed_chunks 路径；CPU 侧车路径见
    test_knowledge_hub_cpu_embedding.py。显式钉住，不受运行环境变量影响。"""
    monkeypatch.setenv("MNEME_EMBED_BACKEND", "legacy")


@pytest.fixture(autouse=True)
def _reset_embed_breaker():
    from services import knowledge_hub_search as khs

    khs._EMBED_STATE["down_until"] = 0.0
    yield
    khs._EMBED_STATE["down_until"] = 0.0


@pytest.mark.asyncio
async def test_embed_breaker_skips_embedding_during_cooldown(monkeypatch):
    calls = {"n": 0}

    async def no_embed(text):
        del text
        calls["n"] += 1
        return None

    monkeypatch.setattr("oprim.embed_chunks.embed_text", no_embed)
    async with SessionLocal() as db:
        r1 = await search_knowledge_base(db, query="检索测试内容", top_k=3)
        r2 = await search_knowledge_base(db, query="检索测试内容", top_k=3)
    assert calls["n"] == 1  # 第二次在冷却期内，不再调用 embed
    assert r1.get("retrieval") == r2.get("retrieval") == "lexical"


@pytest.mark.asyncio
async def test_embed_timeout_falls_back_to_lexical(monkeypatch):
    import asyncio

    from services import knowledge_hub_search as khs

    async def slow_embed(text):
        del text
        await asyncio.sleep(5)
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr("oprim.embed_chunks.embed_text", slow_embed)
    monkeypatch.setattr(khs, "QUERY_EMBED_TIMEOUT_S", 0.05)
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="检索测试内容", top_k=3)
    assert res.get("retrieval") == "lexical"
    assert res["results"]


@pytest.mark.asyncio
async def test_lexical_fallback_rejects_partial_ngram_noise(monkeypatch):
    """库里没有的术语不该靠零散子串凑出结果（2026-10 实测：光合作用 → 物理"作用"）。"""

    async def no_embed(text):
        del text
        return None

    monkeypatch.setattr("oprim.embed_chunks.embed_text", no_embed)
    async with SessionLocal() as db:
        res = await search_knowledge_base(db, query="测试光合作用", top_k=3)
    assert res.get("retrieval") == "lexical"
    assert res["results"] == []

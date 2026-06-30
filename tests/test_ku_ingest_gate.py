"""item 2：KU 录入校验门 + 溯源/源-AI 分离。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.ku_ingest_service import (
    store_curriculum_ku,
    store_curriculum_kus,
    validate_curriculum_ku,
)
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook


def test_gate_rejects_hallucinated_and_incomplete():
    # 残缺：缺描述
    ok, errs = validate_curriculum_ku({"id": "K1", "name": "n", "description": ""})
    assert not ok and any("description" in e for e in errs)
    # 悬空前置（幻觉边）
    ok, errs = validate_curriculum_ku(
        {"id": "K1", "name": "n", "description": "够长的描述内容", "prerequisites": ["GHOST"]},
        known_ku_ids={"K1"},
    )
    assert not ok and any("unknown prerequisite" in e for e in errs)
    # 难度越界
    ok, errs = validate_curriculum_ku({"id": "K1", "name": "n", "description": "够长的描述内容", "difficulty": 5})
    assert not ok and any("difficulty" in e for e in errs)


def test_gate_passes_valid():
    ok, errs = validate_curriculum_ku(
        {"id": "K1", "name": "正数定义", "description": "比0大的数叫正数", "prerequisites": []},
        known_ku_ids={"K1"},
    )
    assert ok and errs == []


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    ids = []
    tb_id = f"tb-{uuid.uuid4().hex[:8]}"
    cl_id = f"c-{uuid.uuid4().hex[:8]}"
    async with factory() as s:
        s.add(Textbook(id=tb_id, subject="math", grade="7", edition="人教", book_name="七上"))
        await s.flush()  # 先落 textbook，满足 cluster/ku 的 DB 级 FK
        s.add(KnowledgeCluster(id=cl_id, textbook_id=tb_id, name="有理数"))
        await s.flush()
        yield s, ids, tb_id, cl_id
        if ids:
            await s.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id.in_(ids)))
        await s.execute(delete(KnowledgeCluster).where(KnowledgeCluster.id == cl_id))
        await s.execute(delete(Textbook).where(Textbook.id == tb_id))
        await s.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_store_writes_provenance_and_separation(db):
    s, ids, tb_id, cl_id = db
    kid = f"TEST-KU-{uuid.uuid4().hex[:8]}"
    ids.append(kid)
    res = await store_curriculum_ku(
        s,
        {"id": kid, "name": "正数定义", "description": "比0大的数叫正数", "difficulty": 0.3,
         "textbook_id": tb_id, "cluster_id": cl_id},
        source_excerpt="教材原文：比0大的数叫做正数。",
        provenance={"chunk_id": "ch-7", "page_hint": "P3"},
        known_ku_ids={kid},
        extract_model="deepseek-test",
    )
    await s.commit()
    assert res["status"] == "stored"
    row = (await s.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == kid))).scalar_one()
    assert row.ai_generated is True
    assert row.verified is True
    assert row.source_excerpt.startswith("教材原文")          # 源内容与 AI 内容分离
    assert row.provenance["chunk_id"] == "ch-7"
    assert row.provenance["extract_model"] == "deepseek-test"  # 溯源


@pytest.mark.asyncio
async def test_batch_rejects_bad_not_stored(db):
    s, ids, tb_id, cl_id = db
    good = f"TEST-KU-{uuid.uuid4().hex[:8]}"
    ids.append(good)
    out = await store_curriculum_kus(
        s,
        [
            {"id": good, "name": "n", "description": "这是一段足够长的知识点描述内容", "textbook_id": tb_id, "cluster_id": cl_id},
            {"id": "", "name": "bad", "description": "x"},  # 残缺 → rejected
        ],
        known_ku_ids={good},
    )
    await s.commit()
    assert out["stored"] == 1 and out["rejected"] == 1

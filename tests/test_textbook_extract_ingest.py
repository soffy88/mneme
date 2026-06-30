"""item 7：教材抽取候选 → 课程校验门落库（含溯源）。合成内核流水线输出，无 LLM/PDF。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook
from services.textbook_extract_service import (
    _candidate_to_curriculum_ku,
    ingest_pipeline_candidates,
)


def test_candidate_mapping_carries_provenance():
    cand = {
        "ku_id": "K-1", "natural_text": "比0大的数叫正数，是有理数的一部分",
        "provenance": {"source": "llm_extract", "chunk_id": "ch-2"},
    }
    ku = _candidate_to_curriculum_ku(cand, "tb1", "cl1")
    assert ku["id"] == "K-1"
    assert ku["provenance"]["chunk_id"] == "ch-2"
    assert ku["_source_excerpt"].startswith("比0大的数")


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    tb = f"tb-{uuid.uuid4().hex[:8]}"
    cl = f"{tb}-auto"
    ids: list[str] = []
    async with factory() as s:
        s.add(Textbook(id=tb, subject="math", grade="7", edition="人教", book_name="七上"))
        await s.flush()
        s.add(KnowledgeCluster(id=cl, textbook_id=tb, name="auto"))
        await s.flush()
        yield s, tb, cl, ids
        if ids:
            await s.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id.in_(ids)))
        await s.execute(delete(KnowledgeCluster).where(KnowledgeCluster.id == cl))
        await s.execute(delete(Textbook).where(Textbook.id == tb))
        await s.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_stores_valid_rejects_empty(db):
    s, tb, cl, ids = db
    good_id = f"K-{uuid.uuid4().hex[:8]}"
    ids.append(good_id)
    pipeline_result = {
        "candidates": [
            {"ku_id": good_id, "natural_text": "比0大的数叫正数，属于有理数",
             "provenance": {"chunk_id": "c1"}},
            {"ku_id": f"K-bad-{uuid.uuid4().hex[:6]}", "natural_text": "",  # 空描述 → 门拒
             "provenance": {"chunk_id": "c2"}},
        ],
        "rejected": [{"ku": {}, "errors": ["x"]}],
        "chunks_processed": 3,
    }
    out = await ingest_pipeline_candidates(
        s, textbook_id=tb, cluster_id=cl, pipeline_result=pipeline_result,
        known_ku_ids={good_id},
    )
    await s.commit()
    assert out["stored"] == 1
    assert out["rejected"] == 1          # 课程门拒 1
    assert out["kernel_rejected"] == 1   # 内核门已拒 1（透出）
    row = (await s.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == good_id))).scalar_one()
    assert row.verified is True
    assert row.source_excerpt.startswith("比0大的数")
    assert row.provenance.get("chunk_id") == "c1"

"""FSRS 权重优化基础设施：日志重放评估 + 候选择优落库。"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.fsrs_optimize_service import (
    evaluate_weights,
    load_cohort_weights,
    reconstruct_review_logs,
    select_best_weights,
)
from services.models import FSRSWeights, InteractionEvent, InteractionSource, User, UserRole

KC = f"FSRSOPT-{uuid.uuid4().hex[:8]}"
COHORT = f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    sids = []
    async with factory() as s:
        yield s, sids
        await s.execute(delete(InteractionEvent).where(InteractionEvent.knowledge_point == KC))
        await s.execute(delete(FSRSWeights).where(FSRSWeights.cohort == COHORT))
        for sid in sids:
            await s.execute(delete(User).where(User.id == sid))
        await s.commit()
    await engine.dispose()


async def _seed(s, sids, n_students=20):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for _ in range(n_students):
        sid = uuid.uuid4()
        sids.append(sid)
        s.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await s.flush()
        # 首答(Good) + 两次间隔复习(Good, 都答对) → 每生 2 个复习对
        for day, rating in [(0, 3), (2, 3), (6, 3)]:
            s.add(InteractionEvent(
                student_id=sid, knowledge_point=KC, source=InteractionSource.quick,
                is_correct=True, fsrs_rating=rating,
                occurred_at=base + timedelta(days=day),
            ))
    await s.flush()


@pytest.mark.asyncio
async def test_evaluate_weights_finite(db):
    s, sids = db
    await _seed(s, sids)
    seqs = await reconstruct_review_logs(s)
    seqs = [q for q in seqs if any(e[1] for e in q)]  # 仅本测试 KC（其余库存数据无害）
    loss, n = evaluate_weights(seqs, None)
    assert n > 0
    assert math.isfinite(loss)


@pytest.mark.asyncio
async def test_select_best_stores_and_beats_default(db):
    s, sids = db
    await _seed(s, sids, n_students=20)  # 40 复习对 ≥ min_reviews

    from fsrs import Scheduler
    default = tuple(Scheduler().parameters)
    perturbed = tuple(p * 1.05 for p in default)   # 备选权重

    result = await select_best_weights(s, [None, perturbed], cohort=COHORT, min_reviews=30)
    await s.commit()

    assert result["stored"] is True
    assert result["n_reviews"] >= 30
    # 最优损失不会高于默认（默认是候选之一）
    assert result["best_logloss"] <= result["default_logloss"] + 1e-9
    row = (await s.execute(select(FSRSWeights).where(FSRSWeights.cohort == COHORT))).scalar_one()
    assert row.n_reviews >= 30
    # load 回读一致
    loaded = await load_cohort_weights(s, cohort=COHORT)
    assert loaded is None or len(loaded) == 21


@pytest.mark.asyncio
async def test_invalid_candidate_scored_inf_not_crash(db):
    s, sids = db
    await _seed(s, sids, n_students=3)
    seqs = await reconstruct_review_logs(s)
    from fsrs import Scheduler
    bad = tuple(p * 10 for p in Scheduler().parameters)  # 超出 FSRS 合法区间
    loss, n = evaluate_weights(seqs, bad)
    assert math.isinf(loss)   # 不崩，记 inf → 永不被选中


@pytest.mark.asyncio
async def test_insufficient_reviews_not_stored(db):
    s, sids = db
    await _seed(s, sids, n_students=2)  # 仅 4 复习对
    result = await select_best_weights(s, [None], cohort=COHORT, min_reviews=30)
    await s.commit()
    assert result["stored"] is False

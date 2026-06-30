"""实证验证 harness：内核对真实作答的预测力（AUC/log-loss）。"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.evaluation_service import compute_predictions, evaluate_model, predictive_metrics
from services.models import InteractionEvent, InteractionSource, User, UserRole

KC = f"EVAL-{uuid.uuid4().hex[:8]}"


def test_predictive_metrics_discriminates():
    """会的学生(全对)预测高、不会的(全错)预测低 → AUC 明显 > 0.5。"""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seqs = []
    for _ in range(10):  # 会：全对
        seqs.append([(base + timedelta(days=i), True, 3, 0.5) for i in range(4)])
    for _ in range(10):  # 不会：全错
        seqs.append([(base + timedelta(days=i), False, 1, 0.5) for i in range(4)])
    m = predictive_metrics(seqs)
    assert m["n"] == 80
    assert m["auc"] is not None and m["auc"] > 0.6   # 区分度明显优于随机
    assert math.isfinite(m["logloss"])


def test_single_class_auc_none():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seqs = [[(base + timedelta(days=i), True, 3, None) for i in range(3)] for _ in range(5)]
    m = predictive_metrics(seqs)
    assert m["auc"] is None          # 只有一类 → AUC 无意义
    assert m["n"] > 0


def test_compute_predictions_in_range():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    preds, actuals = compute_predictions([[(base, True, 3, 0.5), (base + timedelta(days=2), False, 1, 0.5)]])
    assert len(preds) == len(actuals) == 2
    assert all(0.0 < p < 1.0 for p in preds)


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    sids = []
    async with factory() as s:
        yield s, sids
        await s.execute(delete(InteractionEvent).where(InteractionEvent.knowledge_point == KC))
        for sid in sids:
            await s.execute(delete(User).where(User.id == sid))
        await s.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_evaluate_model_end_to_end(db):
    s, sids = db
    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    for known in (True, False):
        for _ in range(8):
            sid = uuid.uuid4()
            sids.append(sid)
            s.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
            await s.flush()
            for i in range(4):
                s.add(InteractionEvent(
                    student_id=sid, knowledge_point=KC, source=InteractionSource.quick,
                    is_correct=known, fsrs_rating=3 if known else 1,
                    occurred_at=base + timedelta(days=i)))
    await s.flush()
    m = await evaluate_model(s)
    assert m["n"] >= 64
    assert m["auc"] is not None and m["auc"] > 0.6
    assert "verdict" in m

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
    fit_and_store_weights,
    fit_weights,
    load_cohort_weights,
    load_weights_for_student,
    reconstruct_review_logs,
    select_best_weights,
)
from services.models import (
    FSRSWeights,
    InteractionEvent,
    InteractionSource,
    User,
    UserRole,
)

KC = f"FSRSOPT-{uuid.uuid4().hex[:8]}"
COHORT = f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    sids = []
    async with factory() as s:
        yield s, sids
        await s.execute(
            delete(InteractionEvent).where(InteractionEvent.knowledge_point == KC)
        )
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
            s.add(
                InteractionEvent(
                    student_id=sid,
                    knowledge_point=KC,
                    source=InteractionSource.quick,
                    is_correct=True,
                    fsrs_rating=rating,
                    occurred_at=base + timedelta(days=day),
                )
            )
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
    perturbed = tuple(p * 1.05 for p in default)  # 备选权重

    result = await select_best_weights(
        s, [None, perturbed], cohort=COHORT, min_reviews=30
    )
    await s.commit()

    assert result["stored"] is True
    assert result["n_reviews"] >= 30
    # 最优损失不会高于默认（默认是候选之一）
    assert result["best_logloss"] <= result["default_logloss"] + 1e-9
    row = (
        await s.execute(select(FSRSWeights).where(FSRSWeights.cohort == COHORT))
    ).scalar_one()
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
    assert math.isinf(loss)  # 不崩，记 inf → 永不被选中


@pytest.mark.asyncio
async def test_insufficient_reviews_not_stored(db):
    s, sids = db
    await _seed(s, sids, n_students=2)  # 仅 4 复习对
    result = await select_best_weights(s, [None], cohort=COHORT, min_reviews=30)
    await s.commit()
    assert result["stored"] is False


def test_fit_weights_returns_valid_or_default(db_unused=None):
    """scipy 拟合：返回合法权重或 None（不优于默认），不崩、不超界。"""
    import math
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    # 合成多张卡片序列（错→对→对，间隔数天）
    seqs = []
    for _ in range(8):
        seqs.append(
            [
                (base, 1, False),
                (base + timedelta(days=2), 3, True),
                (base + timedelta(days=6), 3, True),
            ]
        )
    best, best_loss, default_loss = fit_weights(seqs, maxiter=2)
    assert math.isfinite(default_loss)
    if best is not None:
        assert len(best) == 21
        assert best_loss <= default_loss + 1e-9
        # 合法性：能构造 Scheduler
        from oprim.fsrs_engine import fsrs_review, fsrs_new_card
        from fsrs import Rating

        fsrs_review(
            card_dict=fsrs_new_card(), rating=Rating.Good, now=base, parameters=best
        )


@pytest.mark.asyncio
async def test_fit_and_store_and_student_precedence(db):
    s, sids = db
    await _seed(s, sids, n_students=16)  # 32 复习对 ≥ min_reviews
    # 全体拟合落 global（min_spaced_reviews=0：本测试验证拟合+落库机制，不测 T.3 门控）
    r = await fit_and_store_weights(
        s, cohort=COHORT, min_reviews=30, maxiter=2, min_spaced_reviews=0
    )
    await s.commit()
    assert r["stored"] is True and r["n_reviews"] >= 30

    # 个体优先：写一个 student:{id} 权重，load_weights_for_student 应优先取它
    sid0 = sids[0]
    from fsrs import Scheduler
    from services.fsrs_optimize_service import _store_weights

    custom = tuple(p * 1.02 for p in Scheduler().parameters)
    await _store_weights(s, f"student:{sid0}", custom, 0.5, 99)
    await s.commit()
    loaded = await load_weights_for_student(s, sid0)
    assert loaded is not None and abs(loaded[0] - custom[0]) < 1e-9
    # 清理 student 权重
    from sqlalchemy import delete

    await s.execute(delete(FSRSWeights).where(FSRSWeights.cohort == f"student:{sid0}"))
    await s.commit()

# ── T.3 Powell 拟合门控（moat_eval exp2：massed 日志过拟合防线） ──────────────


def test_count_spaced_reviews_massed_vs_spaced():
    from services.fsrs_optimize_service import count_spaced_reviews

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    massed = [[(base, 3, True), (base + timedelta(hours=2), 3, True),
               (base + timedelta(hours=4), 3, True)]]  # 同日连答：0 个间隔对
    spaced = [[(base, 3, True), (base + timedelta(days=2), 3, True),
               (base + timedelta(days=6), 3, True)]]  # 2 个间隔对
    assert count_spaced_reviews(massed) == 0
    assert count_spaced_reviews(spaced) == 2


@pytest.mark.asyncio
async def test_fit_gate_blocks_massed_logs(db, monkeypatch):
    """复习对够 min_reviews 但全是同日连答 → 不做 Powell 拟合。"""
    s, sids = db
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for _ in range(20):
        sid = uuid.uuid4()
        sids.append(sid)
        s.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await s.flush()
        for hour, rating in [(0, 3), (2, 3), (4, 3)]:  # 同日 3 答 → 2 复习对但 0 间隔对
            s.add(InteractionEvent(
                student_id=sid, knowledge_point=KC, source=InteractionSource.quick,
                is_correct=True, fsrs_rating=rating,
                occurred_at=base + timedelta(hours=hour),
            ))
    await s.flush()
    called = []
    monkeypatch.setattr(
        "services.fsrs_optimize_service.fit_weights",
        lambda *a, **k: called.append(1) or (None, 0.0, 0.0),
    )
    r = await fit_and_store_weights(s, cohort=COHORT, min_reviews=30, min_spaced_reviews=400)
    assert r["stored"] is False
    assert r["reason"] == "insufficient_spaced_reviews"
    assert r["n_spaced_reviews"] == 0 and r["n_reviews"] >= 30
    assert not called  # Powell 根本没被调


@pytest.mark.asyncio
async def test_fit_gate_env_kill_switch(db, monkeypatch):
    """FSRS_FIT_ENABLED=0 一票否决，连日志都不读。"""
    s, _sids = db
    monkeypatch.setenv("FSRS_FIT_ENABLED", "0")
    r = await fit_and_store_weights(s, cohort=COHORT)
    assert r == {"cohort": COHORT, "stored": False, "reason": "fitting_disabled_by_env"}

"""实证验证 harness：内核对真实作答的预测力（AUC/log-loss）+ evaluation_runs 落表/历史查询（T.1）。"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.evaluation_service import (
    compute_predictions,
    evaluate_model,
    predictive_metrics,
)
from services.main import app
from services.models import (
    EvaluationRun,
    InteractionEvent,
    InteractionSource,
    User,
    UserRole,
)

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
    assert m["auc"] is not None and m["auc"] > 0.6  # 区分度明显优于随机
    assert math.isfinite(m["logloss"])


def test_single_class_auc_none():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seqs = [
        [(base + timedelta(days=i), True, 3, None) for i in range(3)] for _ in range(5)
    ]
    m = predictive_metrics(seqs)
    assert m["auc"] is None  # 只有一类 → AUC 无意义
    assert m["n"] > 0


def test_compute_predictions_in_range():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    preds, actuals = compute_predictions(
        [[(base, True, 3, 0.5), (base + timedelta(days=2), False, 1, 0.5)]]
    )
    assert len(preds) == len(actuals) == 2
    assert all(0.0 < p < 1.0 for p in preds)


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    sids: list[uuid.UUID] = []
    run_ids: list[uuid.UUID] = []
    async with factory() as s:
        yield s, sids, run_ids
        await s.execute(
            delete(InteractionEvent).where(InteractionEvent.knowledge_point == KC)
        )
        for sid in sids:
            await s.execute(delete(User).where(User.id == sid))
        if run_ids:
            await s.execute(delete(EvaluationRun).where(EvaluationRun.id.in_(run_ids)))
        await s.commit()
    await engine.dispose()


async def _seed_two_cohorts(s: AsyncSession, sids: list[uuid.UUID]) -> None:
    """8 个全对 + 8 个全错学生，各 4 次作答（可区分 → AUC 可算）。"""
    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    for known in (True, False):
        for _ in range(8):
            sid = uuid.uuid4()
            sids.append(sid)
            s.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
            await s.flush()
            for i in range(4):
                s.add(
                    InteractionEvent(
                        student_id=sid,
                        knowledge_point=KC,
                        source=InteractionSource.quick,
                        is_correct=known,
                        fsrs_rating=3 if known else 1,
                        occurred_at=base + timedelta(days=i),
                    )
                )
    await s.flush()


@pytest.mark.asyncio
async def test_evaluate_model_end_to_end(db):
    s, sids, run_ids = db
    await _seed_two_cohorts(s, sids)
    m = await evaluate_model(s)
    if "run_id" in m:
        run_ids.append(uuid.UUID(m["run_id"]))
    assert m["n"] >= 64
    assert m["auc"] is not None and m["auc"] > 0.6
    assert "verdict" in m


# ── T.1：评估结果落表 + 历史查询 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_model_persists_run(db):
    """全体评估结束后 evaluation_runs 落一行，字段与指标一致。"""
    s, sids, run_ids = db
    await _seed_two_cohorts(s, sids)
    m = await evaluate_model(s)
    assert "run_id" in m
    run_ids.append(uuid.UUID(m["run_id"]))
    run = (
        await s.execute(
            select(EvaluationRun)
            .where(EvaluationRun.id == uuid.UUID(m["run_id"]))
            .execution_options(populate_existing=True)  # 取回 server_default 的 ran_at
        )
    ).scalar_one()
    assert run.ran_at is not None
    assert run.n_events == m["n"] and run.n_events >= 64
    assert run.n_students >= 16
    assert run.auc == m["auc"] and run.auc > 0.6
    assert run.log_loss == m["logloss"] and math.isfinite(run.log_loss)
    assert run.window_start is not None and run.window_end is not None
    assert run.window_start <= run.window_end
    assert run.meta and run.meta.get("verdict") == m["verdict"]


@pytest.mark.asyncio
async def test_evaluation_history_endpoint(db, bypass_auth):
    """GET /v1/moat/evaluation-history 登录可读，返回落表行（倒序、4 位小数）。"""
    s, sids, run_ids = db
    await _seed_two_cohorts(s, sids)
    m = await evaluate_model(s)
    run_ids.append(uuid.UUID(m["run_id"]))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/v1/moat/evaluation-history")
    assert r.status_code == 200
    runs = r.json()["runs"]
    mine = next(x for x in runs if x["id"] == m["run_id"])
    assert mine["n_events"] == m["n"]
    assert mine["auc"] == round(m["auc"], 4)
    assert mine["log_loss"] == round(m["logloss"], 4)
    # 倒序：ran_at 单调不增
    stamps = [x["ran_at"] for x in runs]
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.asyncio
async def test_evaluation_history_anonymous_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/v1/moat/evaluation-history")
    assert r.status_code == 401

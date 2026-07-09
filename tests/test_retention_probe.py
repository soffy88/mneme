"""T.2 保留探针 + 留存三指标。

① 探针混入频率 ~1/20 且确定性可复现（同学生同日期恒同结果）；
② 探针不带答案（检索门红线）且近 7 天已探测过的卡不再抽中；
③ 探针作答落 interaction_events：source=probe + predicted_r，且照常更新 BKT/FSRS；
④ /v1/moat/retention-metrics 三指标数值正确 + 匿名 401。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.main import app
from services.models import (
    InteractionEvent,
    InteractionSource,
    KCMastery,
    MasterySnapshot,
    User,
    UserRole,
    WrongQuestion,
)
from services.review_service import get_due_variants, probe_gate, submit_review_answer

KC_DUE = "RENJIAO-G7-MATH-S-ku-正数和负数的定义"
KC_STABLE = "RENJIAO-G7-MATH-S-ku-有理数的乘法"

_NOW = datetime.now(timezone.utc)


def _due_card() -> dict:
    from oprim.fsrs_engine import fsrs_new_card

    card = fsrs_new_card()
    card["due"] = "2020-01-01T00:00:00+00:00"
    card["last_review"] = "2019-12-01T00:00:00+00:00"
    return card


def _stable_card(now: datetime | None = None) -> dict:
    """远未到期的稳定卡：30 天前复习过、30 天后才到期、stability=30。"""
    from oprim.fsrs_engine import fsrs_new_card

    now = now or _NOW
    card = fsrs_new_card()
    card["stability"] = 30.0
    card["last_review"] = (now - timedelta(days=30)).isoformat()
    card["due"] = (now + timedelta(days=30)).isoformat()
    return card


async def _cleanup_students(db: AsyncSession, sids: list[uuid.UUID]) -> None:
    await db.execute(
        delete(InteractionEvent).where(InteractionEvent.student_id.in_(sids))
    )
    await db.execute(
        delete(MasterySnapshot).where(MasterySnapshot.student_id.in_(sids))
    )
    await db.execute(delete(KCMastery).where(KCMastery.student_id.in_(sids)))
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id.in_(sids)))
    await db.execute(delete(User).where(User.id.in_(sids)))
    await db.commit()


@pytest.fixture()
async def db_probe_student():
    """学生 + 一张到期卡 + 一张远未到期稳定卡（探针候选）+ 稳定卡的原错题。"""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await (
            db.flush()
        )  # 先落 users（kc_mastery 与 users 无 relationship，flush 顺序按表名）
        db.add(
            WrongQuestion(
                id=uuid.uuid4(),
                student_id=sid,
                question_text="x+1=3 求 x",
                correct_answer="2",
                subject="math",
                knowledge_points={KC_STABLE: "x"},
            )
        )
        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=KC_DUE,
                fsrs_card_json=_due_card(),
                p_mastery=0.3,
                p_init=0.2,
                p_transit=0.2,
                p_guess=0.15,
                p_slip=0.12,
            )
        )
        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=KC_STABLE,
                fsrs_card_json=_stable_card(),
                p_mastery=0.9,
                p_init=0.2,
                p_transit=0.2,
                p_guess=0.15,
                p_slip=0.12,
            )
        )
        await db.flush()
        await PriorProvider.warm_up(db)
        yield db, sid
        await _cleanup_students(db, [sid])
    await engine.dispose()


# ── ① 频率与可复现性 ─────────────────────────────────────────────────────────


def test_probe_gate_rate_and_reproducibility():
    """确定性哈希门：~1/20 命中率；同 (学生, 日期) 结果恒定。"""
    d = date(2026, 7, 2)
    sids = [uuid.UUID(int=i) for i in range(4000)]
    hits = sum(1 for s in sids if probe_gate(s, d))
    assert 4000 / 40 <= hits <= 4000 / 10, f"命中 {hits}/4000，偏离 ~1/20 太远"
    # 可复现：重复调用结果恒同（不是 random.random）
    for s in sids[:100]:
        assert probe_gate(s, d) == probe_gate(s, d)
    # 不同日期给同一学生不同的机会（并非恒 False/恒 True）
    days = [date(2026, 7, 2) + timedelta(days=i) for i in range(200)]
    per_day = [probe_gate(sids[0], dd) for dd in days]
    assert any(per_day) and not all(per_day)


# ── ② 混入队列 + 检索门红线 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_mixed_in_and_carries_no_answer(db_probe_student):
    db, sid = db_probe_student
    with patch("services.review_service.probe_gate", return_value=True):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid)
    kcs = [i["ku_id"] for i in items]
    assert KC_DUE in kcs, "到期卡照常在队列"
    assert KC_STABLE in kcs, "探针卡（远未到期稳定卡）应被混入"
    probe_item = next(i for i in items if i["ku_id"] == KC_STABLE)
    # 检索门红线：探针同样只发题面，不带任何答案字段
    assert probe_item.get("requires_retrieval") is True
    for key in ("answer", "variant_answer", "correct_answer"):
        assert key not in probe_item
    # 门未命中 → 不混入
    with patch("services.review_service.probe_gate", return_value=False):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items2 = await get_due_variants(db, sid)
    assert KC_STABLE not in [i["ku_id"] for i in items2]


@pytest.mark.asyncio
async def test_probe_skips_recently_probed_card(db_probe_student):
    """最近 7 天已被探测过的卡不再抽中（唯一候选被排除 → 无探针）。"""
    db, sid = db_probe_student
    db.add(
        InteractionEvent(
            student_id=sid,
            knowledge_point=KC_STABLE,
            source=InteractionSource.probe,
            is_correct=True,
            predicted_r=0.9,
            occurred_at=_NOW - timedelta(days=1),
        )
    )
    await db.flush()
    with patch("services.review_service.probe_gate", return_value=True):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid)
    assert KC_STABLE not in [i["ku_id"] for i in items]


# ── ③ 探针作答落库 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_submit_records_predicted_r_and_updates_fsrs(db_probe_student):
    db, sid = db_probe_student
    old_card = (
        await db.execute(
            select(KCMastery.fsrs_card_json).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == KC_STABLE
            )
        )
    ).scalar_one()
    result = await submit_review_answer(db, sid, KC_STABLE, "2")
    await db.commit()
    assert result["verdict"] == "correct"
    ev = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert ev is not None
    assert ev.source == InteractionSource.probe, "未到期卡的复习作答应识别为探针"
    assert ev.predicted_r is not None and 0.0 < ev.predicted_r < 1.0
    assert ev.is_correct is True
    # 探针照常更新 BKT/FSRS（本就是一次真实检索）
    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == KC_STABLE
            )
        )
    ).scalar_one()
    assert row.n_attempts == 1
    assert row.fsrs_card_json["last_review"] != old_card["last_review"]


@pytest.mark.asyncio
async def test_due_card_submit_stays_review_source(db_probe_student):
    """到期卡的正常复习不被误判为探针（source=review，predicted_r 空）。"""
    db, sid = db_probe_student
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="2+2=?",
            correct_answer="4",
            subject="math",
            knowledge_points={KC_DUE: "x"},
        )
    )
    await db.flush()
    result = await submit_review_answer(db, sid, KC_DUE, "4")
    await db.commit()
    assert result["verdict"] == "correct"
    ev = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert ev is not None
    assert ev.source == InteractionSource.review
    assert ev.predicted_r is None


# ── ④ 指标端点 ───────────────────────────────────────────────────────────────

_FAKE_NOW = datetime(2030, 1, 15, 12, 0, tzinfo=timezone.utc)
_S1 = uuid.uuid5(uuid.NAMESPACE_URL, "mneme-t2-metrics-s1")
_S2 = uuid.uuid5(uuid.NAMESPACE_URL, "mneme-t2-metrics-s2")
_S3 = uuid.uuid5(uuid.NAMESPACE_URL, "mneme-t2-metrics-s3")


def _ev(
    sid: uuid.UUID,
    kc: str,
    source: InteractionSource,
    when: datetime,
    *,
    correct: bool = True,
    predicted_r: float | None = None,
) -> InteractionEvent:
    return InteractionEvent(
        student_id=sid,
        knowledge_point=kc,
        source=source,
        is_correct=correct,
        predicted_r=predicted_r,
        occurred_at=when,
    )


@pytest.fixture()
async def db_metrics():
    """造三指标数据（now 固定 2030，与真实/其他测试数据的时间窗隔离）。

    d7（cohort=首交互 ∈ [now-56d, now-8d]）：
      s1 首交互 now-20d，且在第 7 天(now-13d)有交互 → 留存；
      s2 首交互 now-20d，之后无 → 不留存；s3 首交互 now-3d → 不入 cohort。
      期望 value=0.5, n=2。
    完成率（近14天）：s1 在 now-2d 有 1 个 review 组合（分子1）；
      s2 有一张 due=now-5d 至今未复习的卡（欠账1）→ value=0.5, n=2。
    探针校准：(0.9,对)(0.9,错)(0.6,对)(0.3,对) → 均值0.675/召回0.75/n=4。
    """
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sids = [_S1, _S2, _S3]
        await _cleanup_students(db, sids)
        # probe_calibration 是全量口径：清掉历史遗留 probe 事件，保证断言确定
        await db.execute(
            delete(InteractionEvent).where(
                InteractionEvent.source == InteractionSource.probe
            )
        )
        for sid in sids:
            db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await db.flush()  # 先落 users，再插 FK 引用行
        now = _FAKE_NOW
        q = InteractionSource.quick
        # d7
        db.add(_ev(_S1, "T2-KC-D7", q, now - timedelta(days=20)))
        db.add(_ev(_S1, "T2-KC-D7", q, now - timedelta(days=13)))  # 第 7 天回访
        db.add(_ev(_S2, "T2-KC-D7", q, now - timedelta(days=20)))
        db.add(_ev(_S3, "T2-KC-D7", q, now - timedelta(days=3)))
        # 完成率：s1 一次 review；s2 一张逾期未复习卡
        db.add(_ev(_S1, "T2-KC-A", InteractionSource.review, now - timedelta(days=2)))
        overdue_card = _stable_card(now)
        overdue_card["due"] = (now - timedelta(days=5)).isoformat()
        overdue_card["last_review"] = (now - timedelta(days=10)).isoformat()
        db.add(
            KCMastery(
                student_id=_S2,
                knowledge_point="T2-KC-B",
                fsrs_card_json=overdue_card,
                p_mastery=0.5,
                p_init=0.2,
                p_transit=0.2,
                p_guess=0.15,
                p_slip=0.12,
            )
        )
        # 探针校准
        for r, ok in ((0.9, True), (0.9, False), (0.6, True), (0.3, True)):
            db.add(
                _ev(
                    _S1,
                    "T2-KC-P",
                    InteractionSource.probe,
                    now - timedelta(days=1),
                    correct=ok,
                    predicted_r=r,
                )
            )
        await db.commit()
        yield db
        await _cleanup_students(db, sids)
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_metrics_values(db_metrics):
    from services.retention_service import retention_metrics

    m = await retention_metrics(db_metrics, now=_FAKE_NOW)
    assert m["d7_retention"] == {"value": 0.5, "n": 2}
    assert m["review_completion_rate"] == {"value": 0.5, "n": 2}
    cal = m["probe_calibration"]
    assert cal["predicted_r_mean"] == 0.675
    assert cal["actual_recall"] == 0.75
    assert cal["n"] == 4
    assert cal["buckets"]["0.0-0.5"] == {
        "predicted_r_mean": 0.3,
        "actual_recall": 1.0,
        "n": 1,
    }
    assert cal["buckets"]["0.5-0.8"] == {
        "predicted_r_mean": 0.6,
        "actual_recall": 1.0,
        "n": 1,
    }
    assert cal["buckets"]["0.8-1.0"] == {
        "predicted_r_mean": 0.9,
        "actual_recall": 0.5,
        "n": 2,
    }


@pytest.mark.asyncio
async def test_retention_metrics_endpoint_auth(bypass_auth):
    """登录可读（返回三指标键）；匿名 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/moat/retention-metrics")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("d7_retention", "review_completion_rate", "probe_calibration"):
        assert key in body


@pytest.mark.asyncio
async def test_retention_metrics_anonymous_401():
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/moat/retention-metrics")
    assert resp.status_code == 401

"""
B.1 DoD 测试：CognitiveStore 装配层
=====================================
1. process_interaction 写库正确（kc_mastery 更新 + interaction_events 只增不改 + mastery_snapshots upsert）
2. mastery_overview 按 effective_mastery 升序（薄弱在前）
3. 交互事件只增不改
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.cognitive_service import mastery_overview, process_interaction
from services.models import (
    EffortfulGain,
    InteractionEvent,
    KCMastery,
    KnowledgeUnit,
    MasterySnapshot,
    User,
    UserRole,
)


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """自访问正向测试统一绕过 IDOR 鉴权。"""


@pytest.fixture(scope="function")
async def db_with_student():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"150{str(uuid.uuid4())[:8]}", role=UserRole.student)
        session.add(user)
        await session.commit()
        await PriorProvider.warm_up(session)

        yield session, student_id

        await session.execute(delete(EffortfulGain).where(EffortfulGain.student_id == student_id))
        await session.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == student_id))
        await session.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
        await session.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_process_interaction_writes_kc_mastery(db_with_student):
    """process_interaction 应更新 kc_mastery 表中对应记录。"""
    session, student_id = db_with_student
    kc_id = "GDMATH-CONIC-01"

    result = await process_interaction(session, student_id, kc_id, is_correct=False)
    await session.commit()

    row = (
        await session.execute(
            select(KCMastery)
            .where(KCMastery.student_id == student_id)
            .where(KCMastery.knowledge_point == kc_id)
        )
    ).scalar_one_or_none()

    assert row is not None, "kc_mastery 记录应被创建"
    assert row.p_mastery is not None
    assert result["p_mastery"] == pytest.approx(row.p_mastery, abs=1e-3)
    print(f"  kc_mastery 写库正确: p_mastery={row.p_mastery:.4f} ✓")


@pytest.mark.asyncio
async def test_interaction_events_append_only(db_with_student):
    """交互事件必须只增不改——同一 KC 三次交互产生 3 条记录，每条 is_correct 与输入一致。"""
    session, student_id = db_with_student
    kc_id = "GDMATH-SET-01"
    now = datetime.now(timezone.utc)

    sequence = [False, True, False]
    for i, correct in enumerate(sequence):
        await process_interaction(session, student_id, kc_id, is_correct=correct, now=now + timedelta(hours=i))
        await session.commit()

    events = (
        await session.execute(
            select(InteractionEvent)
            .where(InteractionEvent.student_id == student_id)
            .where(InteractionEvent.knowledge_point == kc_id)
            .order_by(InteractionEvent.occurred_at)
        )
    ).scalars().all()

    assert len(events) == 3, f"应有 3 条事件记录，实际 {len(events)}"
    for event, expected_correct in zip(events, sequence):
        assert event.is_correct == expected_correct, "事件 is_correct 应与输入一致（只增不改）"
    print(f"  交互事件只增不改验证通过: {len(events)} 条 ✓")


@pytest.mark.asyncio
async def test_mastery_snapshot_upserted(db_with_student):
    """每次 process_interaction 后应 upsert 本月快照，同月第二次不新增行。"""
    session, student_id = db_with_student
    kc_id = "GDMATH-SEQ-01"
    now = datetime.now(timezone.utc)

    await process_interaction(session, student_id, kc_id, is_correct=False, now=now)
    await session.commit()
    await process_interaction(session, student_id, kc_id, is_correct=True, now=now + timedelta(hours=2))
    await session.commit()

    count = (
        await session.execute(
            select(func.count()).select_from(MasterySnapshot)
            .where(MasterySnapshot.student_id == student_id)
            .where(MasterySnapshot.knowledge_point == kc_id)
        )
    ).scalar_one()

    assert count == 1, f"同月同 KC 只应有 1 条快照（upsert），实际 {count}"
    snapshot = (
        await session.execute(
            select(MasterySnapshot)
            .where(MasterySnapshot.student_id == student_id)
            .where(MasterySnapshot.knowledge_point == kc_id)
        )
    ).scalar_one()
    assert snapshot.long_term_mastery is not None
    print(f"  mastery_snapshot upsert 正确: long_term={snapshot.long_term_mastery:.4f} ✓")


@pytest.mark.asyncio
async def test_mastery_overview_sorted_ascending(db_with_student):
    """mastery_overview 应按 effective_mastery 升序返回（薄弱 KC 在前）。"""
    session, student_id = db_with_student
    now = datetime.now(timezone.utc)

    # 给两个 KC 制造明显不同的掌握度
    for _ in range(6):
        await process_interaction(session, student_id, "GDMATH-CONIC-01", is_correct=True, now=now)
        await session.commit()
    for _ in range(2):
        await process_interaction(session, student_id, "GDMATH-SET-01", is_correct=False, now=now)
        await session.commit()

    items = await mastery_overview(session, student_id, now=now)
    assert len(items) >= 2

    effective_vals = [item["effective_mastery"] for item in items]
    assert effective_vals == sorted(effective_vals), \
        f"掌握度应升序排列，实际: {effective_vals}"
    print(f"  mastery_overview 升序排列验证通过: {[round(v,3) for v in effective_vals]} ✓")


@pytest.mark.asyncio
async def test_mastery_overview_has_peer_percentile(db_with_student):
    """mastery_overview 结果中每项应含 peer_percentile 字段。"""
    session, student_id = db_with_student
    now = datetime.now(timezone.utc)

    await process_interaction(session, student_id, "GDMATH-CONIC-01", is_correct=True, now=now)
    await session.commit()

    items = await mastery_overview(session, student_id, now=now)
    assert len(items) >= 1
    for item in items:
        assert "peer_percentile" in item, "每项应含 peer_percentile 字段"
    print("  peer_percentile 字段存在 ✓")


@pytest.mark.asyncio
async def test_phase2_difficulty_autolookup_from_ku(db_with_student):
    """Phase 2（IRT 通电）：未显式给 difficulty 时按 kc_id 自动取 KU 难度落库；
    非 KU 知识点则 item_difficulty 保持 None（行为不变）。"""
    session, student_id = db_with_student

    ku = (await session.execute(
        select(KnowledgeUnit.id, KnowledgeUnit.difficulty).limit(1)
    )).first()
    if ku is None:
        pytest.skip("DB 无 KnowledgeUnit，跳过 Phase 2 自动取难度测试")
    ku_id, ku_diff = ku

    # 真实 KU 知识点 → 自动取难度并落库
    await process_interaction(session, student_id, ku_id, is_correct=True, source="quick")
    await session.commit()
    rec = (await session.execute(
        select(InteractionEvent.item_difficulty)
        .where(InteractionEvent.student_id == student_id)
        .where(InteractionEvent.knowledge_point == ku_id)
    )).scalar_one()
    assert rec == pytest.approx(ku_diff)

    # 非 KU 知识点 → 保持 None
    fake_kc = "GDMATH-NOT-A-KU-zzz"
    await process_interaction(session, student_id, fake_kc, is_correct=True, source="quick")
    await session.commit()
    rec2 = (await session.execute(
        select(InteractionEvent.item_difficulty)
        .where(InteractionEvent.student_id == student_id)
        .where(InteractionEvent.knowledge_point == fake_kc)
    )).scalar_one()
    assert rec2 is None


@pytest.mark.asyncio
async def test_effortful_gain_recorded_on_struggled_correct(db_with_student):
    """努力收益（M-F）：吃力但答对 → 记录 EffortfulGain = struggle×retention_delta；
    不吃力则不记录。"""
    session, student_id = db_with_student
    qid = uuid.uuid4()

    # 吃力 + 答对 → FSRS 稳定性↑ → 记录努力收益
    await process_interaction(
        session, student_id, "GDMATH-CONIC-01", is_correct=True,
        struggled=True, time_spent_seconds=90, question_id=qid, source="quick",
    )
    await session.commit()

    rows = (await session.execute(
        select(EffortfulGain).where(EffortfulGain.student_id == student_id)
    )).scalars().all()
    assert len(rows) == 1
    g = rows[0]
    assert g.struggle_score > 0
    assert g.retention_delta > 0
    assert g.effortful_gain == pytest.approx(g.struggle_score * g.retention_delta, abs=1e-3)

    # 不吃力（无 struggled、无用时）→ 不记录
    await process_interaction(
        session, student_id, "GDMATH-SET-01", is_correct=True, source="quick",
    )
    await session.commit()
    rows2 = (await session.execute(
        select(EffortfulGain).where(EffortfulGain.student_id == student_id)
    )).scalars().all()
    assert len(rows2) == 1  # 仍只有 1 条


@pytest.mark.asyncio
async def test_effortful_gains_endpoint(db_with_student):
    """GET /v1/effortful-gains/{sid} 返回 top_gains（ASGI 端到端，对当前源码）。"""
    from httpx import AsyncClient, ASGITransport
    from services.main import app

    session, student_id = db_with_student
    qid = uuid.uuid4()
    await process_interaction(
        session, student_id, "GDMATH-CONIC-01", is_correct=True,
        struggled=True, time_spent_seconds=90, question_id=qid, source="quick",
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/effortful-gains/{student_id}")
    assert r.status_code == 200
    body = r.json()
    assert "top_gains" in body
    assert len(body["top_gains"]) == 1
    g = body["top_gains"][0]
    assert g["effortful_gain"] > 0
    assert g["question_id"] == str(qid)


@pytest.mark.asyncio
async def test_weakness_roots_surfaces_weak_prereq(db_with_student):
    """前置图谱归因：薄弱 KU 的薄弱前置应被上溯出来。"""
    from services.cognitive_service import weakness_roots
    session, student_id = db_with_student

    row = (await session.execute(
        select(KnowledgeUnit.id, KnowledgeUnit.prerequisites)
        .where(func.jsonb_array_length(KnowledgeUnit.prerequisites) > 0)
        .limit(1)
    )).first()
    if row is None:
        pytest.skip("DB 无带前置的 KU")
    ku_id, prereqs = row
    prereq_id = prereqs[0]

    # 该 KU 与其前置都答错 → 都薄弱
    await process_interaction(session, student_id, ku_id, is_correct=False)
    await process_interaction(session, student_id, prereq_id, is_correct=False)
    await session.commit()

    roots = await weakness_roots(session, student_id, mastery_threshold=0.95)
    entry = next((r for r in roots if r["ku_id"] == ku_id), None)
    assert entry is not None, "薄弱 KU 应出现在归因结果中"
    assert any(g["ku_id"] == prereq_id for g in entry["weak_prerequisites"]), "薄弱前置应被上溯"


@pytest.mark.asyncio
async def test_jol_predicted_confidence_and_calibration(db_with_student):
    """JOL：predicted_confidence 落库 + /v1/calibration 算 brier/overconfidence。"""
    from httpx import AsyncClient, ASGITransport
    from services.main import app
    session, student_id = db_with_student

    # 高估：0.9 把握却错；低估：0.2 把握却对
    await process_interaction(session, student_id, "GDMATH-CONIC-01", is_correct=False,
                              predicted_confidence=0.9, source="quick")
    await process_interaction(session, student_id, "GDMATH-SET-01", is_correct=True,
                              predicted_confidence=0.2, source="quick")
    await session.commit()

    recs = sorted(r for r in (await session.execute(
        select(InteractionEvent.predicted_confidence).where(InteractionEvent.student_id == student_id)
    )).scalars().all() if r is not None)
    assert recs == [pytest.approx(0.2), pytest.approx(0.9)]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/calibration/{student_id}")
    assert r.status_code == 200
    b = r.json()
    assert b["n"] == 2
    # brier = ((0.9-0)^2 + (0.2-1)^2)/2 = (0.81+0.64)/2 = 0.725
    assert b["brier"] == pytest.approx(0.725, abs=1e-3)
    # mean_pred=0.55, acc=0.5 → overconfidence=+0.05
    assert b["overconfidence"] == pytest.approx(0.05, abs=1e-3)


@pytest.mark.asyncio
async def test_weekly_digest_streak(db_with_student):
    """留存引擎：连续学习天数从真实活动算；本周摘要计数正确。"""
    from services.cognitive_service import weekly_digest
    session, student_id = db_with_student
    now = datetime.now(timezone.utc)
    # 今天/昨天/前天连续，再加 5 天前（断开）
    for delta in (0, 1, 2, 5):
        await process_interaction(session, student_id, "GDMATH-CONIC-01", is_correct=True,
                                  source="quick", now=now - timedelta(days=delta))
    await session.commit()

    dig = await weekly_digest(session, student_id, now=now)
    assert dig["current_streak"] == 3, dig
    assert dig["active_today"] is True
    assert dig["days_active_7d"] == 4
    assert dig["n_interactions_7d"] == 4


@pytest.mark.asyncio
async def test_daily_report(db_with_student):
    """家长日报：当天活动汇成一句话。"""
    from services.cognitive_service import daily_report
    session, student_id = db_with_student
    now = datetime.now(timezone.utc)
    await process_interaction(session, student_id, "GDMATH-CONIC-01", is_correct=True, source="quick", now=now)
    await process_interaction(session, student_id, "GDMATH-SET-01", is_correct=False, source="quick", now=now)
    await session.commit()
    rep = await daily_report(session, student_id, day=now.date())
    assert rep["n_interactions"] == 2
    assert rep["distinct_kcs"] == 2
    assert "学习日报" in rep["report_text"]

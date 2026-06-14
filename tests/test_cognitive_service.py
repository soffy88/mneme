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
from services.cognitive_service import mastery_overview, process_interaction, review_queue
from services.models import (
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    User,
    UserRole,
)


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
    print(f"  peer_percentile 字段存在 ✓")

"""T.5 集成测试：FIRe-lite 前置信用回写接线（omodul cognitive + 服务层，Master §4.8）。

红线覆盖：
- 综合 KU 答对 → verified 前置 due 被顺延、卡片 D/S/last_review 逐位不变、
  BKT P(L) 不变、fire_credit 事件落库带 κ 与顺延前后 due。
- 答错不触发；unverified 前置边不触发；κ<τ 不触发。
- fire_credit 不级联（链上仅直接前置被回写，前置的前置不动）。
- 20h 集中练习去抖：非真实检索不触发。
- 默认关（FIRE_ENABLED 未设 / =0 时无任何回写）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from obase.cognitive_types import fsrs_new_card
from obase.config import settings
from obase.prior_provider import PriorProvider
from oprim.fsrs_engine import fsrs_review
from services.cognitive_service import process_interaction
from services.models import (
    InteractionEvent,
    InteractionSource,
    KCMastery,
    KnowledgeCluster,
    KnowledgeUnit,
    MasterySnapshot,
    Textbook,
    User,
    UserRole,
)

NOW = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """自访问正向测试统一绕过 IDOR 鉴权。"""


@pytest.fixture(autouse=True)
def _fire_on(monkeypatch):
    """exp4 未达接线门槛 → 生产默认关；测试显式开启（个别测试再覆盖）。"""
    monkeypatch.setenv("FIRE_ENABLED", "1")


def _reviewed_card(
    *, days_ago_list: list[float], now: datetime, due_in_days: float | None = 1.0
) -> dict:
    """构造一张真实 py-fsrs 卡：按给定天数序列做 Good 复习。

    due_in_days 非 None 时把 due 拉到 now+该天数（临期卡——FIRe 只在
    候选 now+κ·S 晚于原 due 时才有净顺延，测试需要可控的临期状态）。"""
    from fsrs import Rating

    card = fsrs_new_card()
    for d in sorted(days_ago_list, reverse=True):
        card = fsrs_review(
            card_dict=card, rating=Rating.Good, now=now - timedelta(days=d)
        )
    if due_in_days is not None:
        card["due"] = (now + timedelta(days=due_in_days)).isoformat()
    return card


@pytest.fixture(scope="function")
async def fire_env():
    """学生 + KU 链 gp←p1←c（全 verified）+ p2(unverified 前置) + p3(低掌握前置)。

    c.prerequisites = [p1, p2, p3]；p1.prerequisites = [gp]。
    p1/gp/p3 均有既有 KCMastery（真实 FSRS 卡 + 指定 p_mastery）。
    """
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    sfx = uuid.uuid4().hex[:6]
    tb_id = f"test-tb-fire-{sfx}"
    cl_id = f"test-cl-fire-{sfx}"
    ids = {k: f"test-ku-fire-{k}-{sfx}" for k in ("c", "p1", "p2", "p3", "gp")}

    async with factory() as db:
        student_id = uuid.uuid4()
        db.add(
            User(
                id=student_id,
                phone=f"151{str(uuid.uuid4().int)[:8]}",
                role=UserRole.student,
            )
        )
        db.add(
            Textbook(
                id=tb_id,
                subject="math",
                grade="高一",
                edition="测试版",
                book_name="FIRe 测试教材",
            )
        )
        await db.flush()
        db.add(KnowledgeCluster(id=cl_id, textbook_id=tb_id, name="FIRe 章节"))
        await db.flush()
        for key, prereqs, verified in [
            ("gp", [], True),
            ("p1", [ids["gp"]], True),
            ("p2", [], False),  # unverified 前置边不参与
            ("p3", [], True),
            ("c", [ids["p1"], ids["p2"], ids["p3"]], True),
        ]:
            db.add(
                KnowledgeUnit(
                    id=ids[key],
                    textbook_id=tb_id,
                    cluster_id=cl_id,
                    name=f"KU-{key}",
                    prerequisites=prereqs,
                    related_kus=[],
                    question_types=["解答题"],
                    mastery_levels=[],
                    verified=verified,
                )
            )
        # 既有前置掌握状态：p1/gp/p2 高掌握（κ=0.45>τ），p3 低掌握（κ=0.2<τ）
        for key, pm in [("p1", 0.9), ("gp", 0.9), ("p2", 0.9), ("p3", 0.4)]:
            db.add(
                KCMastery(
                    student_id=student_id,
                    knowledge_point=ids[key],
                    p_mastery=pm,
                    long_term_mastery=pm,
                    p_init=0.3,
                    p_transit=0.2,
                    p_guess=0.15,
                    p_slip=0.1,
                    fsrs_card_json=_reviewed_card(days_ago_list=[12.0, 6.0], now=NOW),
                    last_interaction_at=NOW - timedelta(days=6),
                    n_attempts=2,
                )
            )
        await db.commit()
        await PriorProvider.warm_up(db)

        yield db, student_id, ids

        await db.execute(
            delete(MasterySnapshot).where(MasterySnapshot.student_id == student_id)
        )
        await db.execute(
            delete(InteractionEvent).where(InteractionEvent.student_id == student_id)
        )
        await db.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await db.execute(
            delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id)
        )
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
        )
        await db.execute(delete(Textbook).where(Textbook.id == tb_id))
        await db.execute(delete(User).where(User.id == student_id))
        await db.commit()
    await engine.dispose()


async def _mastery_row(db, student_id, kc_id) -> KCMastery:
    return (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == kc_id,
            )
        )
    ).scalar_one()


async def _fire_events(db, student_id) -> list[InteractionEvent]:
    return list(
        (
            await db.execute(
                select(InteractionEvent).where(
                    InteractionEvent.student_id == student_id,
                    InteractionEvent.source == InteractionSource.fire_credit,
                )
            )
        )
        .scalars()
        .all()
    )


async def test_fire_postpones_verified_prereq_only_due(fire_env):
    """答对综合 KU → p1 due 顺延；D/S/last_review 逐位不变；P(L) 不变；
    unverified p2 与 κ<τ 的 p3 不动；fire_credit 事件带 κ 与前后 due。"""
    db, student_id, ids = fire_env
    before = {
        k: dict((await _mastery_row(db, student_id, ids[k])).fsrs_card_json)
        for k in ("p1", "p2", "p3", "gp")
    }
    pm_before = {
        k: (await _mastery_row(db, student_id, ids[k])).p_mastery
        for k in ("p1", "p2", "p3", "gp")
    }

    await process_interaction(db, student_id, ids["c"], True, now=NOW)
    await db.commit()

    # p1（verified，κ=0.5×0.9=0.45≥τ）：仅 due 顺延
    p1 = await _mastery_row(db, student_id, ids["p1"])
    assert p1.fsrs_card_json["due"] > before["p1"]["due"]
    for field in ("stability", "difficulty", "last_review", "state", "step"):
        assert p1.fsrs_card_json[field] == before["p1"][field]  # D/S/R 逐位不变
    assert p1.p_mastery == pytest.approx(pm_before["p1"])  # BKT P(L) 不动

    # unverified 前置边 p2：完全不动
    p2 = await _mastery_row(db, student_id, ids["p2"])
    assert p2.fsrs_card_json == before["p2"]
    # κ<τ 的 p3：完全不动
    p3 = await _mastery_row(db, student_id, ids["p3"])
    assert p3.fsrs_card_json == before["p3"]

    events = await _fire_events(db, student_id)
    assert [e.knowledge_point for e in events] == [ids["p1"]]
    meta = events[0].fire_meta
    assert meta["trigger_kc_id"] == ids["c"]
    assert meta["kappa"] == pytest.approx(0.45)
    assert meta["due_before"] == before["p1"]["due"]
    assert meta["due_after"] == p1.fsrs_card_json["due"]
    assert meta["trigger_event_id"] is not None


async def test_fire_no_cascade_to_grandparent(fire_env):
    """不级联：c 答对只回写直接前置 p1；p1 的前置 gp 无事件、due 不动。"""
    db, student_id, ids = fire_env
    gp_before = dict((await _mastery_row(db, student_id, ids["gp"])).fsrs_card_json)

    await process_interaction(db, student_id, ids["c"], True, now=NOW)
    await db.commit()

    gp = await _mastery_row(db, student_id, ids["gp"])
    assert gp.fsrs_card_json == gp_before
    events = await _fire_events(db, student_id)
    assert all(e.knowledge_point != ids["gp"] for e in events)


async def test_fire_not_triggered_on_wrong_answer(fire_env):
    """答错不触发。"""
    db, student_id, ids = fire_env
    await process_interaction(db, student_id, ids["c"], False, now=NOW)
    await db.commit()
    assert await _fire_events(db, student_id) == []


async def test_fire_debounced_massed_practice_not_retrieval(fire_env):
    """20h 去抖：同日重复答对（非真实检索）不再触发——p1 只有一条 fire_credit。"""
    db, student_id, ids = fire_env
    await process_interaction(db, student_id, ids["c"], True, now=NOW)
    await db.commit()
    await process_interaction(
        db, student_id, ids["c"], True, now=NOW + timedelta(hours=1)
    )
    await db.commit()
    events = await _fire_events(db, student_id)
    assert len([e for e in events if e.knowledge_point == ids["p1"]]) == 1


async def test_fire_disabled_by_default(fire_env, monkeypatch):
    """exp4 决策：默认关。FIRE_ENABLED 未设/=0 时无任何回写。"""
    db, student_id, ids = fire_env
    monkeypatch.delenv("FIRE_ENABLED", raising=False)
    p1_before = dict((await _mastery_row(db, student_id, ids["p1"])).fsrs_card_json)

    await process_interaction(db, student_id, ids["c"], True, now=NOW)
    await db.commit()

    assert await _fire_events(db, student_id) == []
    p1 = await _mastery_row(db, student_id, ids["p1"])
    assert p1.fsrs_card_json == p1_before


async def test_fire_credit_source_never_cascades():
    """结构守卫：source='fire_credit' 的交互即使走主链也不触发 FIRe（不级联红线）。"""
    from omodul.cognitive import (
        InteractionConfig,
        InteractionInput,
        process_interaction_workflow,
    )
    from obase.cognitive_store import InMemoryStore

    store = InMemoryStore()
    store._verified_prereqs = {"kc-c": ["kc-p"]}
    student = uuid.uuid4()
    # 预置前置状态（高掌握 + 已排程卡）
    state_p, _ = await store.get_or_create(student, "kc-p")
    state_p.p_mastery = 0.9
    await store.save(
        student, "kc-p", state_p, _reviewed_card(days_ago_list=[12.0, 6.0], now=NOW)
    )

    config = InteractionConfig(fire_enabled=True)
    result = await process_interaction_workflow(
        config,
        InteractionInput(
            student_id=student,
            ku_id="kc-c",
            is_correct=True,
            source="fire_credit",
            now=NOW,
        ),
        store,
    )
    assert result["status"] == "completed"
    # 主链事件本身 source=fire_credit（人造输入），但前置 kc-p 无任何回写事件
    assert not [
        e
        for e in store._events
        if e.get("source") == "fire_credit" and e["knowledge_point"] == "kc-p"
    ]

    # 对照：同条件 source='review'（真实检索）会触发
    store2 = InMemoryStore()
    store2._verified_prereqs = {"kc-c": ["kc-p"]}
    state_p2, _ = await store2.get_or_create(student, "kc-p")
    state_p2.p_mastery = 0.9
    await store2.save(
        student, "kc-p", state_p2, _reviewed_card(days_ago_list=[12.0, 6.0], now=NOW)
    )
    await process_interaction_workflow(
        config,
        InteractionInput(
            student_id=student, ku_id="kc-c", is_correct=True, source="review", now=NOW
        ),
        store2,
    )
    fired = [e for e in store2._events if e.get("source") == "fire_credit"]
    assert len(fired) == 1 and fired[0]["knowledge_point"] == "kc-p"
    assert fired[0]["fire_meta"]["kappa"] == pytest.approx(0.45)

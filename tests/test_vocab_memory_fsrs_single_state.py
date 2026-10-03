"""FSRS 复习阶梯的**调度状态唯一性**契约（CME-P0.5 / 收口项 5）。

要钉死的是一句话：**一个词只能有一份调度状态**。

阶梯（图片 → 语义 → 词源 → 真实句）曾经有个危险读法：把它做成 4 张独立 FSRS 卡。
那会让 2,761 个单词变成 1.1 万张卡、复习量 ×4，而且同一个词在两个地方各有一份
`stability`，谁也不认识谁。2026-10-03 人决策定了：**每词 1 张卡、1 个 KC**，
阶梯是同一张卡内的分阶段揭示。

所以这里验证的不是「阶梯能不能渲染」（那在 test_vocab_memory_engine.py），
而是**渲染阶梯不会产生第二份调度状态**：

- 反复调 `GetMemoryNode`/渲染阶梯 → `kc_mastery` 行数不变、`fsrs_card_json` 不变；
- 一次真实作答（走 `submit_vocab_review` → `process_interaction` 唯一写路径）
  → 只产生 1 行 `vocab-{id}`；
- 再多次复习 → 仍是同一行（`UPDATE` 而非 `INSERT`），阶梯随之换阶段；
- 全程不产生任何第二张 MemoryNode。

这条测试的价值在于它是**反证**：如果哪天有人把阶梯改成多卡，这里会立刻炸。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.models import KCMastery, User, UserRole, VocabularyItem, VocabularyMemoryNode
from services.vocab_memory import (
    STAGE_LEARNING,
    STAGE_REVIEW_EARLY,
    STAGE_REVIEW_LATE,
    STAGE_REVIEW_MID,
    render_review_ladder,
    resolve_stage,
    vocab_kc,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_session():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def enrolled_student(db_session: AsyncSession):
    """一个真实学生 + 一个词 + 一条已生成并落库的 MemoryNode。"""
    sid = uuid.uuid4()
    db_session.add(User(id=sid, phone=f"159{str(uuid.uuid4())[:8]}", role=UserRole.student))
    vid = f"test-ladder-{uuid.uuid4().hex[:12]}"
    db_session.add(
        VocabularyItem(
            id=vid, word="abandon", frequency_rank=9999, frequency_band=5,
            source="test", meaning_cn="放弃；抛弃", pos="verb",
        )
    )
    db_session.add(
        VocabularyMemoryNode(
            vocabulary_item_id=vid,
            tier="B",
            core_image="船长松开缆绳弃船逃离",
            semantic_core={"image": "船长松手", "meaning": "放手不再负责",
                           "logic": "放手→失去控制→放弃"},
            scene="暴风雨中船长跳上救生艇",
            recall_question="船长松开缆绳弃船是什么动作？",
            answer="abandon",
            context_tier=3,
            context_evidence=[{"sentence_id": "s0", "text": "The team abandoned the project."}],
            quality_score=1.0,
            verified=True,
        )
    )
    await db_session.commit()
    yield sid, vid
    await db_session.execute(
        text("DELETE FROM kc_mastery WHERE student_id = :s"), {"s": sid}
    )
    await db_session.execute(
        text("DELETE FROM interaction_events WHERE student_id = :s"), {"s": sid}
    )
    await db_session.execute(
        text("DELETE FROM mastery_snapshots WHERE student_id = :s"), {"s": sid}
    )
    await db_session.execute(
        text("DELETE FROM vocabulary_memory_nodes WHERE vocabulary_item_id = :v"), {"v": vid}
    )
    await db_session.execute(text("DELETE FROM vocabulary_items WHERE id = :v"), {"v": vid})
    await db_session.execute(text("DELETE FROM users WHERE id = :s"), {"s": sid})
    await db_session.commit()


async def _card_row(db: AsyncSession, sid, kp: str):
    return (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == kp
            )
        )
    ).scalar_one_or_none()


async def _count_nodes(db: AsyncSession, vid: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(VocabularyMemoryNode)
            .where(VocabularyMemoryNode.vocabulary_item_id == vid)
        )
    ).scalar_one()


async def test_rendering_the_ladder_creates_no_scheduling_state(
    db_session: AsyncSession, enrolled_student
):
    """纯渲染不得碰 kc_mastery —— 阶梯是**读**出来的，不是算出来的。"""
    from services.mcp_router import tool_get_memory_node

    sid, vid = enrolled_student
    kp = vocab_kc(vid)

    for stage in (STAGE_LEARNING, STAGE_REVIEW_EARLY, STAGE_REVIEW_LATE):
        out = await tool_get_memory_node(db_session, vid, stage=stage)
        assert out["found"] is True
        assert out["ladder"]["stage"] == stage
        assert out["ladder"]["kc"] == kp

    assert await _card_row(db_session, sid, kp) is None, "渲染阶梯竟然写了掌握度"
    assert await _count_nodes(db_session, vid) == 1, "渲染阶梯竟然复制了 MemoryNode"


async def test_one_word_yields_exactly_one_kc_row_across_many_reviews(
    db_session: AsyncSession, enrolled_student
):
    """反复作答仍是**同一行**（UPDATE），不 INSERT 第二份调度状态。"""
    from services.vocab_service import submit_vocab_review

    sid, vid = enrolled_student
    kp = vocab_kc(vid)

    for remembered in (True, True, False, True):
        await submit_vocab_review(db_session, sid, vid, remembered)

    rows = (
        (
            await db_session.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid,
                    KCMastery.knowledge_point.like("vocab-%"),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"一个词出现了 {len(rows)} 份调度状态"
    assert rows[0].knowledge_point == kp
    # 阶梯渲染仍复用同一个 KC 名，不会因为复习次数变出第二个 id
    assert render_review_ladder({"vocabulary_item_id": vid})["kc"] == kp


async def test_staged_reveal_advances_with_the_single_card(
    db_session: AsyncSession, enrolled_student
):
    """阶段由**那一张卡**的状态决定；卡变�� → 揭示层数变，但行数不变。"""
    from services.mcp_router import tool_get_memory_node
    from services.vocab_service import submit_vocab_review

    sid, vid = enrolled_student
    kp = vocab_kc(vid)

    # 首次：无卡 → learning，全展开
    first = await tool_get_memory_node(db_session, vid, student_id=sid)
    assert first["ladder"]["all_shown"] is True
    assert first["ladder"]["stage"] == STAGE_LEARNING

    await submit_vocab_review(db_session, sid, vid, True)

    n_after = (
        await db_session.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.student_id == sid, KCMastery.knowledge_point.like("vocab-%"))
        )
    ).scalar_one()
    assert n_after == 1

    card = (await _card_row(db_session, sid, kp)).fsrs_card_json
    stage = resolve_stage(card)
    assert stage in (STAGE_LEARNING, STAGE_REVIEW_EARLY, STAGE_REVIEW_MID, STAGE_REVIEW_LATE)

    after = await tool_get_memory_node(db_session, vid, student_id=sid)
    assert after["ladder"]["stage"] == stage
    assert after["ladder"]["kc"] == kp

    # 无论第几次复习，都仍是同一行
    await submit_vocab_review(db_session, sid, vid, True)
    n_final = (
        await db_session.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.student_id == sid, KCMastery.knowledge_point.like("vocab-%"))
        )
    ).scalar_one()
    assert n_final == 1
    assert await _count_nodes(db_session, vid) == 1


async def test_expanded_deep_dive_does_not_write(db_session: AsyncSession, enrolled_student):
    """「再看一层」只影响露出多少 —— 绝不能顺手把这次点击记成一次复习。

    必须在**有折叠**的阶段比：首次（learning）本来就全展开，expanded 加不加了。
    """
    from services.mcp_router import tool_get_memory_node

    sid, vid = enrolled_student
    shallow = await tool_get_memory_node(
        db_session, vid, stage=STAGE_REVIEW_LATE, expanded=0
    )
    deep = await tool_get_memory_node(
        db_session, vid, stage=STAGE_REVIEW_LATE, expanded=3
    )

    assert shallow["ladder"]["hidden_count"] > 0, "该阶段本该有折叠层，否则这个断言没意义"
    assert deep["ladder"]["hidden_count"] < shallow["ladder"]["hidden_count"]
    assert deep["ladder"]["stage"] == shallow["ladder"]["stage"]
    assert await _card_row(db_session, sid, vocab_kc(vid)) is None
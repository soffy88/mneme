"""记忆节点的**数据库路径**集成测试（Context → 契约 → 门禁 → upsert → 读回 → 阶梯）。

为什么单独一个文件：`tests/test_vocab_memory_engine.py` 全是纯函数 + 假 db，不碰
数据库，所以它**证明不了** SQL 能不能跑。这一层专门验证：

- `vocabulary_memory_nodes` 的 DDL 与 ORM 一致（列名/约束/默认值写错只有这里会炸）；
- upsert 按 **vocabulary_item_id** 而不是 `word`（word 在本表不唯一）；
- tier=5 时 DB CHECK 真的强制 `context_absence_reason`；
- 读回路径能把既有事实层（词根/搭配）挂进复习阶梯。

**不打 LLM**：`tool_generate_memory_node` 依赖的 provider 在本机可能不可用
（Veya 配额耗尽时整个测试会变成网络测试）。这里把 `generate_memory_nodes` 换成一个
返回固定 JSON 的桩，于是除「模型本身」以外的每一环都是真的。桩本身在
`test_vocab_memory_engine.py` 里已单独测过契约校验。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.models import VocabularyItem, VocabularyMemoryNode

pytestmark = pytest.mark.asyncio

# mneme_test 是**手工补列**出来的（`alembic upgrade head` 被既有漂移
# vocabulary_items.language 挡住，见 STATUS 2026-10-02），所以 NCE 课程链的
# 三张表在测试库里**根本不存在**。这里按 b2c3d4e5f6a7 的 DDL 幂等补齐它们 ——
# 只补 Context Retriever 真正 JOIN 到的那三张，不去"修"整个漂移（那是独立 epic）。
_NCE_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS lessons (
    id VARCHAR(100) PRIMARY KEY,
    book_id VARCHAR(100) NOT NULL,
    lesson_key VARCHAR(200) NOT NULL,
    title VARCHAR(200) NOT NULL,
    source_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS timed_sentences (
    id VARCHAR(100) PRIMARY KEY,
    lesson_id VARCHAR(100) NOT NULL REFERENCES lessons(id),
    source_order INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER,
    english_text TEXT,
    chinese_text TEXT,
    raw_text TEXT,
    source_line INTEGER,
    source_entry_key VARCHAR(200) NOT NULL
);
CREATE TABLE IF NOT EXISTS sentence_vocabulary_occurrences (
    id VARCHAR(100) PRIMARY KEY,
    sentence_id VARCHAR(100) NOT NULL REFERENCES timed_sentences(id),
    vocabulary_item_id VARCHAR(100) NOT NULL REFERENCES vocabulary_items(id),
    occurrence_index INTEGER NOT NULL,
    token_start INTEGER,
    token_end INTEGER
);
"""

STUB_NODE = {
    "word": "abandon",
    "core_image": "船长松开缆绳弃船逃离",
    "semantic_core": {"image": "船长松手", "meaning": "放手不再负责", "logic": "放手→放弃"},
    "scene": "暴风雨中船长跳上救生艇",
    "family": [{"word": "abandoned", "meaning_cn": "被遗弃的"}],
    "sound_hook": "啊·班等",
    "spelling_hook": "pre·fix 是预先固定的",
    "recall_question": "船长松开缆绳弃船是什么动作？",
    "answer": "abandon",
    "image_prompt": "A captain letting go of ship ropes in a storm, cartoon educational style",
}


@pytest.fixture
async def db_session():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        for stmt in _NCE_BOOTSTRAP.split(";"):
            if stmt.strip():
                await session.execute(text(stmt))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
async def vocab_pair(db_session: AsyncSession):
    """两个**同名**的 VocabularyItem —— 逼出「按 word 更新会串行」的经典 bug。"""
    ids = []
    for suffix in ("a", "b"):
        row = VocabularyItem(
            id=f"test-mem-{uuid.uuid4().hex[:12]}",
            word="abandon",
            frequency_rank=9999,
            frequency_band=5,
            source="test",
            meaning_cn="放弃；抛弃",
        )
        db_session.add(row)
        ids.append(row.id)
    await db_session.flush()
    yield ids
    await db_session.execute(
        text("DELETE FROM vocabulary_memory_nodes WHERE vocabulary_item_id = ANY(:ids)"),
        {"ids": ids},
    )
    await db_session.execute(
        text("DELETE FROM vocabulary_items WHERE id = ANY(:ids)"), {"ids": ids}
    )
    await db_session.commit()


def _stub_generate(nodes: list):
    """造一个「假 oprim 生成函数」：按输入长度回同样长的结果。

    注意 `oprim` 是 vendor 副本，工具函数在调用时才 `from oprim._vocab_memory_generate
    import generate_memory_nodes`，所以 patch 模块属性即可生效（不是 patch 导入方）。
    """

    async def _fake(entries, **kwargs):
        assert len(nodes) == len(entries), "桩必须与输入等长（契约要求等长同序）"
        return list(nodes)

    return _fake


@pytest.fixture
def stub_llm(monkeypatch):
    def _install(nodes):
        monkeypatch.setattr(
            "oprim._vocab_memory_generate.generate_memory_nodes", _stub_generate(nodes)
        )

    return _install


@pytest.fixture
async def family_word(db_session: AsyncSession):
    """`abandoned` —— 让 family_network 的正向追溯真的能查到东西。

    桩里的 family 词如果不在库里，resolve_family 会返回空、FAMILY_TRACEABLE 判不过
    （这是**正确**行为：LLM 随手编的派生词不能进库）。所以这里种一个真词。
    """
    wid = f"test-fam-{uuid.uuid4().hex[:12]}"
    db_session.add(
        VocabularyItem(
            id=wid,
            word="abandoned",
            frequency_rank=9998,
            frequency_band=5,
            source="test",
            meaning_cn="被遗弃的",
        )
    )
    await db_session.commit()
    yield wid
    await db_session.execute(text("DELETE FROM vocabulary_items WHERE id = :i"), {"i": wid})
    await db_session.commit()


@pytest.fixture
async def nce_context(db_session: AsyncSession, vocab_pair):
    """给两个同名词各挂一条**真实** NCE 句（走 sentence_vocabulary_occurrences）。

    没有它，Context Retriever 必然返回 tier=5 → HAS_CONTEXT 不过 → verified=False。
    那个行为是对的（无语境不记假绿），但那样就测不到 A/B 层的完整路径了。
    """
    lesson_id = f"test-lesson-{uuid.uuid4().hex[:8]}"
    sentence_id = f"test-sent-{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(
            "INSERT INTO lessons (id, book_id, lesson_key, title, source_order) "
            "VALUES (:lid, 'test-book', 'test-lesson', 'Lesson 32', 1)"
        ),
        {"lid": lesson_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO timed_sentences (id, lesson_id, source_order, start_ms, "
            "english_text, chinese_text, source_entry_key) "
            "VALUES (:sid, :lid, 1, 0, :en, :cn, 'entry-1')"
        ),
        {
            "sid": sentence_id,
            "lid": lesson_id,
            "en": "The team abandoned the project after three months.",
            "cn": "团队三个月后放弃了项目。",
        },
    )
    for i, vid in enumerate(vocab_pair):
        await db_session.execute(
            text(
                "INSERT INTO sentence_vocabulary_occurrences "
                "(id, sentence_id, vocabulary_item_id, occurrence_index) "
                "VALUES (:oid, :sid, :vid, 0)"
            ),
            {"oid": f"test-occ-{uuid.uuid4().hex[:8]}", "sid": sentence_id, "vid": vid},
        )
    await db_session.commit()
    yield sentence_id
    await db_session.execute(
        text("DELETE FROM sentence_vocabulary_occurrences WHERE sentence_id = :s"),
        {"s": sentence_id},
    )
    await db_session.execute(
        text("DELETE FROM timed_sentences WHERE id = :s"), {"s": sentence_id}
    )
    await db_session.execute(text("DELETE FROM lessons WHERE id = :l"), {"l": lesson_id})
    await db_session.commit()


async def test_generate_then_read_back(db_session, vocab_pair, nce_context, family_word, stub_llm):
    """完整正向路径：真实语境句 → 生成 → 9 门禁全过 → 落库 → 读回 → 首次全展开。

    顺带验证「无词根数据也能生成」：测试库里 vocabulary_affixes 无行，属正常降级。
    """
    import services.mcp_router as mr

    stub_llm([dict(STUB_NODE)])
    target = vocab_pair[0]
    out = await mr.tool_generate_memory_node(db_session, target, persist=True)
    await db_session.commit()

    assert out["persisted"] is True
    assert out["row"]["verified"] is True
    assert out["row"]["context_tier"] == 3
    assert out["memory_input"]["context"]["sentences"][0]["sentence_id"] == nce_context

    got = await mr.tool_get_memory_node(db_session, target)
    assert got["found"] is True
    assert got["word"] == "abandon"
    assert got["verified"] is True
    # 首次（无 card）= 全展开
    assert got["ladder"]["all_shown"] is True
    assert got["ladder"]["kc"] == f"vocab-{target}"
    # family 成员必须带库内真实 id，不能只是一串字符串
    assert [f["vocabulary_item_id"] for f in out["row"]["family_network"]] == [family_word]


async def test_upsert_targets_by_id_not_word(db_session, vocab_pair, stub_llm):
    """同名两行都生成 → 必须各写各的。按 word 更新会把一方的内容覆盖到另一方。"""
    import services.mcp_router as mr

    stub_llm([dict(STUB_NODE)])
    for target in vocab_pair:
        await mr.tool_generate_memory_node(db_session, target, persist=True)
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(VocabularyMemoryNode).where(
                    VocabularyMemoryNode.vocabulary_item_id.in_(vocab_pair)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.vocabulary_item_id for r in rows} == set(vocab_pair)


async def test_upsert_is_idempotent_not_duplicating(db_session, vocab_pair, stub_llm):
    import services.mcp_router as mr

    stub_llm([dict(STUB_NODE)])
    target = vocab_pair[0]
    await mr.tool_generate_memory_node(db_session, target, persist=True)
    await mr.tool_generate_memory_node(db_session, target, persist=True)
    await db_session.commit()
    n = (
        await db_session.execute(
            text("SELECT count(*) FROM vocabulary_memory_nodes WHERE vocabulary_item_id = :v"),
            {"v": target},
        )
    ).scalar()
    assert n == 1


async def test_db_rejects_context_tier_five_without_reason(db_session, vocab_pair):
    """tier=5（无真实语境）必须写明原因，CHECK 约束强制。

    没有这条，「这个学生学的教材里没有这个词」与「我们还没接入教材句」无法区分，
    教材优先这条产品承诺会静默消失。
    """
    import sqlalchemy.exc as saexc

    row = VocabularyMemoryNode(
        vocabulary_item_id=vocab_pair[0],
        tier="C",
        core_image="船长松开缆绳弃船逃离",
        semantic_core={"image": "x", "meaning": "y", "logic": "z"},
        recall_question="船长松开缆绳弃船是什么动作？",
        answer="abandon",
        context_tier=5,
    )
    db_session.add(row)
    with pytest.raises(saexc.IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_generation_degrades_without_inventing(db_session, vocab_pair, stub_llm):
    """桩返回 None（契约未过）→ 不落库、不假装成功。"""
    import services.mcp_router as mr

    stub_llm([None])
    target = vocab_pair[0]
    out = await mr.tool_generate_memory_node(db_session, target, persist=True)
    assert out["node"] is None
    assert out["row"] is None
    assert out["persisted"] is False
    assert out["reason"]
    n = (
        await db_session.execute(
            text("SELECT count(*) FROM vocabulary_memory_nodes WHERE vocabulary_item_id = :v"),
            {"v": target},
        )
    ).scalar()
    assert n == 0


async def test_get_missing_node_is_not_an_error(db_session):
    import services.mcp_router as mr

    out = await mr.tool_get_memory_node(db_session, "does-not-exist")
    assert out["found"] is False
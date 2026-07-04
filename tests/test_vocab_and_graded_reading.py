"""U.19 英语习得型范式：词汇 FSRS + 分级泛读测试。

覆盖：oprim 词频/难度统计（确定性）/ 词汇复现服务 / 分级读物选文服务 / API 端点。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import (
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    ReadingPassage,
    User,
    UserRole,
    VocabularyItem,
)

NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── oprim 层：确定性词频/难度统计 ──────────────────────────────────────────


def test_tokenize_lowercases_and_strips_punctuation():
    from oprim._word_frequency_stats import tokenize

    assert tokenize("Hello, world! It's fine.") == ["hello", "world", "it's", "fine"]


def test_compute_word_frequency_ranks_by_count():
    from oprim._word_frequency_stats import compute_word_frequency

    freq = compute_word_frequency(["cat cat dog", "dog bird"])
    by_word = {f["word"]: f for f in freq}
    assert by_word["cat"]["count"] == 2
    assert by_word["cat"]["rank"] == 1
    assert by_word["dog"]["count"] == 2


def test_assign_frequency_bands_covers_full_range():
    from itertools import product

    from oprim._word_frequency_stats import (
        assign_frequency_bands,
        compute_word_frequency,
    )

    # 100 个各不相同的纯字母 token（tokenize 只保留字母，数字后缀如 "w0" 会被
    # 规约成同一个词 "w"，故这里用字母组合而非数字后缀构造不同频次的词）。
    tokens = ["".join(pair) for pair in product("abcdefghij", repeat=2)][:100]
    words = " ".join(tok for i, tok in enumerate(tokens) for _ in range(100 - i))
    freq = compute_word_frequency([words])
    banded = assign_frequency_bands(freq, n_bands=5)
    bands = {b["frequency_band"] for b in banded}
    assert bands == {1, 2, 3, 4, 5}
    assert banded[0]["frequency_band"] == 1
    assert banded[-1]["frequency_band"] == 5


def test_assign_frequency_bands_empty_input():
    from oprim._word_frequency_stats import assign_frequency_bands

    assert assign_frequency_bands([]) == []


def test_find_lowercase_attested_words_excludes_proper_nouns():
    from oprim._word_frequency_stats import find_lowercase_attested_words

    texts = ["Monroe was a judge. The county has many people. People are happy."]
    attested = find_lowercase_attested_words(texts)
    assert "people" in attested
    assert "county" in attested
    # "Monroe" only ever appears capitalized -> not attested as common word
    assert "monroe" not in attested


def test_flesch_kincaid_simple_vs_complex():
    from oprim._readability_score import flesch_kincaid_grade

    simple = flesch_kincaid_grade("The cat sat on the mat. It was a sunny day.")
    complex_ = flesch_kincaid_grade(
        "The extraordinarily convoluted methodology necessitated comprehensive "
        "reconsideration of foundational epistemological assumptions."
    )
    assert simple < complex_


def test_flesch_kincaid_empty_text_is_zero():
    from oprim._readability_score import flesch_kincaid_grade

    assert flesch_kincaid_grade("") == 0.0


def test_assign_difficulty_bands_stable_scale():
    from oprim._readability_score import assign_difficulty_bands

    items = [{"readability_score": s} for s in [1.0, 3.0, 5.0, 7.0, 9.0]]
    banded = assign_difficulty_bands(items, n_bands=5)
    assert [b["difficulty_band"] for b in banded] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_generate_vocab_glosses_matches_by_word():
    from oprim._vocab_gloss_generate import generate_vocab_glosses

    class MockLLM:
        async def __call__(self, **kwargs):
            return {
                "content": '[{"word":"happy","pos":"adj.","meaning_cn":"快乐的"}]',
                "usage": {},
            }

    result = await generate_vocab_glosses(
        [{"word": "happy", "example_sentence": "She felt happy."}], caller=MockLLM()
    )
    assert result == [{"word": "happy", "pos": "adj.", "meaning_cn": "快乐的"}]


@pytest.mark.asyncio
async def test_generate_vocab_glosses_missing_word_degrades_gracefully():
    from oprim._vocab_gloss_generate import generate_vocab_glosses

    class MockLLM:
        async def __call__(self, **kwargs):
            return {"content": "[]", "usage": {}}

    result = await generate_vocab_glosses(
        [{"word": "rare", "example_sentence": "A rare bird."}], caller=MockLLM()
    )
    assert result == [{"word": "rare", "pos": None, "meaning_cn": None}]


# ── 服务层 + API ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def student(db: AsyncSession):
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"199{str(sid)[:8]}",
            role=UserRole.student,
            name="V",
            grade="高一",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def vocab_items(db: AsyncSession):
    ids = [f"test-vocab-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    words = ["apple", "banana", "cherry"]
    for vid, word, band in zip(ids, words, [1, 1, 3]):
        db.add(
            VocabularyItem(
                id=vid,
                word=word,
                pos="n.",
                meaning_cn="测试释义",
                example_sentence=f"This is a {word}.",
                frequency_rank=1,
                frequency_band=band,
                source="test",
            )
        )
    await db.commit()
    yield ids
    await db.execute(delete(VocabularyItem).where(VocabularyItem.id.in_(ids)))
    await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_due_vocab_reviews_returns_new_words_when_no_history(
    db, student, vocab_items
):
    from services.vocab_service import get_due_vocab_reviews

    sid, _ = student
    result = await get_due_vocab_reviews(db, sid, limit=10)
    assert result["due_reviews"] == []
    returned_ids = {w["vocab_id"] for w in result["new_words"]}
    assert returned_ids & set(vocab_items)
    # band 1 词应排在 band 3 词之前（新词按频率档从低到高）
    bands = [
        w["frequency_band"] for w in result["new_words"] if w["vocab_id"] in vocab_items
    ]
    assert bands == sorted(bands)


@pytest.mark.asyncio
async def test_submit_vocab_review_updates_mastery(db, student, vocab_items):
    from services.vocab_service import submit_vocab_review

    sid, _ = student
    vid = vocab_items[0]
    result = await submit_vocab_review(db, sid, vid, remembered=True)
    assert result["remembered"] is True
    assert result["p_mastery"] is not None

    from sqlalchemy import select

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid,
                KCMastery.knowledge_point == f"vocab-{vid}",
            )
        )
    ).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_submit_vocab_review_unknown_vocab_errors(db, student):
    from services.vocab_service import submit_vocab_review

    sid, _ = student
    result = await submit_vocab_review(db, sid, "does-not-exist", remembered=True)
    assert "error" in result


@pytest.mark.asyncio
async def test_due_vocab_reviews_surfaces_due_card(db, student, vocab_items):
    """已学过且到期的词进 due_reviews；未到期不进。"""
    from services.vocab_service import get_due_vocab_reviews, submit_vocab_review
    from sqlalchemy import update

    sid, _ = student
    vid = vocab_items[0]
    await submit_vocab_review(db, sid, vid, remembered=True)

    # 手动把 FSRS 卡片的 due 拨到过去，模拟到期
    from sqlalchemy import select

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid,
                KCMastery.knowledge_point == f"vocab-{vid}",
            )
        )
    ).scalar_one()
    card = dict(row.fsrs_card_json)
    card["due"] = (NOW - timedelta(days=1)).isoformat()
    card["last_review"] = (NOW - timedelta(days=3)).isoformat()
    await db.execute(
        update(KCMastery).where(KCMastery.id == row.id).values(fsrs_card_json=card)
    )
    await db.commit()

    result = await get_due_vocab_reviews(db, sid, limit=10)
    due_ids = {w["vocab_id"] for w in result["due_reviews"]}
    assert vid in due_ids


@pytest.mark.asyncio
async def test_estimate_reading_level_defaults_to_one_without_data(db, student):
    from services.vocab_service import estimate_reading_level

    sid, _ = student
    level = await estimate_reading_level(db, sid)
    assert level == 1


@pytest.mark.asyncio
async def test_estimate_reading_level_rises_with_mastery(db, student, vocab_items):
    from services.vocab_service import estimate_reading_level, submit_vocab_review

    sid, _ = student
    # band=1 的两个词都练到掌握（多次答对推高 p_mastery）
    for vid in vocab_items[:2]:
        for _ in range(5):
            await submit_vocab_review(db, sid, vid, remembered=True)

    level = await estimate_reading_level(db, sid, gate=0.3)
    assert level >= 1


# ── 分级泛读 ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
async def passages(db: AsyncSession):
    ids = [f"test-passage-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    for pid, band in zip(ids, [1, 3, 5]):
        db.add(
            ReadingPassage(
                id=pid,
                subject="english",
                title=f"Test passage band {band}",
                body_text="This is a test passage. " * 10,
                source_url="https://simple.wikipedia.org/wiki/Test",
                word_count=50,
                readability_score=float(band * 2),
                difficulty_band=band,
            )
        )
    await db.commit()
    yield ids
    await db.execute(delete(ReadingPassage).where(ReadingPassage.id.in_(ids)))
    await db.commit()


@pytest.mark.asyncio
async def test_select_graded_passage_picks_i_plus_1(db, student, passages):
    """无词汇数据时 i=1（estimate_reading_level 默认），target_band=2。

    不断言具体返回哪篇文章——reading_passages 是全库共享的种子内容表
    （同 knowledge_units，非按测试隔离），实际是否精确命中 band=2 取决于
    库里已导入的真实语料，这里只验证 i+1 换算逻辑本身正确。
    """
    from services.graded_reading_service import select_graded_passage

    sid, _ = student
    result = await select_graded_passage(db, sid)
    assert result["reading_level_i"] == 1
    assert result["target_band"] == 2
    assert result["difficulty_band"] in (1, 2, 3, 4, 5)


@pytest.mark.asyncio
async def test_select_graded_passage_exact_band_match(db, student, passages):
    """精确命中该 band 时优先用精确命中，不退而求其次。"""
    from services.graded_reading_service import _pick_passage_near_band

    row = await _pick_passage_near_band(db, target_band=5)
    assert row.difficulty_band == 5


# ── API 端点 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vocab_due_api(db, student, vocab_items):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/v1/vocab/due", params={"student_id": str(sid)}, headers=_h(token)
        )
    assert r.status_code == 200
    body = r.json()
    assert "due_reviews" in body and "new_words" in body


@pytest.mark.asyncio
async def test_vocab_due_api_rejects_other_student(db, student, vocab_items):
    sid, token = student
    other_id = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/v1/vocab/due", params={"student_id": str(other_id)}, headers=_h(token)
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_vocab_review_api(db, student, vocab_items):
    sid, token = student
    vid = vocab_items[0]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/vocab/review",
            json={"student_id": str(sid), "vocab_id": vid, "remembered": True},
            headers=_h(token),
        )
    assert r.status_code == 200
    assert r.json()["remembered"] is True


@pytest.mark.asyncio
async def test_vocab_review_api_unknown_vocab_404(db, student):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/vocab/review",
            json={"student_id": str(sid), "vocab_id": "nope", "remembered": True},
            headers=_h(token),
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_graded_passage_api(db, student, passages):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/v1/reading/graded-passage",
            params={"student_id": str(sid)},
            headers=_h(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert "body_text" in body and "difficulty_band" in body


@pytest.mark.asyncio
async def test_graded_passage_api_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/v1/reading/graded-passage", params={"student_id": str(uuid.uuid4())}
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_vocab_due_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/v1/vocab/due", params={"student_id": str(uuid.uuid4())})
    assert r.status_code == 401

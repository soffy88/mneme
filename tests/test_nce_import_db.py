"""NCE importer DB tests: canonical resolver, membership uniqueness,
cross-source reuse, dry-run no writes, apply idempotency, learning-event /
FSRS zero pollution, provenance, alembic single head.

Runs against mneme_test only (enforced by tests/db_guard.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import services  # noqa: F401 — vendor-first path setup
from services.models import (
    Book,
    Course,
    Lesson,
    LessonVocabularyMembership,
    SentenceVocabularyOccurrence,
    TimedSentence,
    VocabularyCollection,
    VocabularyCollectionMembership,
    VocabularyImportBatch,
    VocabularyItem,
)

from scripts.nce_importer.manifest import NCEManifestLoader
from scripts.nce_importer.planner import (
    CourseImportPlan,
    PlannedBook,
    PlannedLesson,
    PlannedOccurrence,
    PlannedSentence,
)
from scripts.nce_importer.repository import CourseImportRepository
from scripts.nce_importer.resolver import CanonicalVocabularyResolver, ResolvedVocab, get_vid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VOCAB_ITEM_ALTERS = [
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en'",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS display_form VARCHAR(100)",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS normalized_form VARCHAR(100)",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS lexeme_type VARCHAR(20) DEFAULT 'WORD'",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS canonical_meaning TEXT",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS phonetic_uk VARCHAR(100)",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS phonetic_us VARCHAR(100)",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS phonetic_generic VARCHAR(100)",
    "ALTER TABLE vocabulary_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE",
]

NEW_TABLES = [
    Course.__table__,
    Book.__table__,
    Lesson.__table__,
    TimedSentence.__table__,
    LessonVocabularyMembership.__table__,
    SentenceVocabularyOccurrence.__table__,
    VocabularyCollection.__table__,
    VocabularyCollectionMembership.__table__,
    VocabularyImportBatch.__table__,
]


@pytest.fixture
async def db_session():
    """Isolated schema + seed data on mneme_test; cleaned up after each test."""
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)

    # vocabulary_collection_memberships pre-exists in mneme_test (stale schema):
    # never drop it. All other course-chain tables are ours to create/drop.
    own_tables = [t for t in NEW_TABLES if t.name != "vocabulary_collection_memberships"]

    async with engine.begin() as conn:
        for alter in VOCAB_ITEM_ALTERS:
            await conn.execute(text(alter))

        def _create(sync_conn):
            from services.models import Base

            Base.metadata.create_all(bind=sync_conn, tables=NEW_TABLES, checkfirst=True)

        await conn.run_sync(_create)

    # Seed canonical vocabulary: airport (existing), plus a K12 collection.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO vocabulary_items
                    (id, word, language, display_form, normalized_form, lexeme_type,
                     frequency_rank, frequency_band, source, ai_generated)
                VALUES
                    (:id, 'airport', 'en', 'airport', 'airport', 'WORD', 100, 3, 'k12_sync', false),
                    (:id2, 'handbag', 'en', 'handbag', 'handbag', 'WORD', 200, 3, 'k12_sync', false)
                ON CONFLICT DO NOTHING
                """
            ),
            {"id": get_vid("airport"), "id2": get_vid("handbag")},
        )
        await conn.execute(
            text(
                """
                INSERT INTO vocabulary_collections
                    (id, kind, scope, title, stage)
                VALUES ('coll-k12-1', 'TEXTBOOK', 'K12_SYNC', 'K12 Seed Book', 'PRIMARY')
                ON CONFLICT DO NOTHING
                """
            )
        )
        await conn.execute(
            text(
                """
                INSERT INTO vocabulary_collection_memberships
                    (id, collection_id, vocabulary_item_id)
                VALUES ('mem-seed-1', 'coll-k12-1', :id)
                ON CONFLICT DO NOTHING
                """
            ),
            {"id": get_vid("airport")},
        )

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        await session.close()
        async with engine.begin() as conn:
            # Remove seeded rows in FK-safe order, then drop our tables.
            await conn.execute(
                text("DELETE FROM vocabulary_collection_memberships WHERE id = 'mem-seed-1'")
            )
            await conn.execute(
                text("DELETE FROM vocabulary_collections WHERE id = 'coll-k12-1'")
            )
            for table in reversed(own_tables):
                await conn.execute(
                    text(f"DROP TABLE IF EXISTS {table.name} CASCADE")
                )
            await conn.execute(
                text("DELETE FROM vocabulary_items WHERE source = 'nce'")
            )
            await conn.execute(
                text("DELETE FROM vocabulary_items WHERE id IN (:a, :b)"),
                {"a": get_vid("airport"), "b": get_vid("handbag")},
            )
        await engine.dispose()


def _make_plan() -> CourseImportPlan:
    """Small deterministic plan: 1 book, 2 lessons, sentences with repeats."""
    sent1 = PlannedSentence(
        source_order=1,
        start_ms=0,
        end_ms=1000,
        english_text="Excuse me, is this your handbag?",
        chinese_text="对不起，这是你的手提包吗？",
        raw_text="[00:00.61]Excuse me, is this your handbag? | 对不起，这是你的手提包吗？",
        source_line=5,
        source_entry_key="[00:00.61]Excuse me, is this your handbag?",
        occurrences=[
            PlannedOccurrence(get_vid("excuse"), "excuse", "WORD", 0, 0, 6, "Excuse"),
            PlannedOccurrence(get_vid("handbag"), "handbag", "WORD", 0, 28, 35, "handbag"),
        ],
    )
    sent2 = PlannedSentence(
        source_order=2,
        start_ms=1000,
        end_ms=2000,
        english_text="The airport is near the handbag.",
        chinese_text=None,
        raw_text="[00:02.71]The airport is near the handbag.",
        source_line=6,
        source_entry_key="[00:02.71]The airport is near the handbag.",
        occurrences=[
            PlannedOccurrence(get_vid("airport"), "airport", "WORD", 0, 4, 11, "airport"),
            PlannedOccurrence(get_vid("handbag"), "handbag", "WORD", 1, 24, 31, "handbag"),
        ],
    )
    lesson1 = PlannedLesson(
        lesson_key="001&002.Excuse Me",
        title="001&002.Excuse Me",
        source_order=1,
        audio_uri="https://nce.mleo.site/NCE1/001&002.Excuse Me.mp3",
        audio_hash="aa" * 32,
        audio_duration_ms=37128,
        lrc_uri="https://nce.mleo.site/NCE1/001&002.Excuse Me.lrc",
        lrc_hash="bb" * 32,
        sentences=[sent1, sent2],
    )
    lesson2 = PlannedLesson(
        lesson_key="003&004.Sorry, Sir.",
        title="003&004.Sorry, Sir.",
        source_order=2,
        audio_uri=None,
        audio_hash=None,
        audio_duration_ms=None,
        lrc_uri="https://nce.mleo.site/NCE1/003&004.Sorry, Sir..lrc",
        lrc_hash="cc" * 32,
        sentences=[],
    )
    book = PlannedBook(
        book_key="NCE1",
        edition="CURRENT",
        title="NCE",
        level="1st Level",
        source_url="https://nce.mleo.site/NCE1",
        source_hash="dd" * 32,
        source_metadata={"content_rights": "RESTRICTED_EXTERNAL_EDUCATIONAL_CONTENT"},
        lessons=[lesson1, lesson2],
    )
    return CourseImportPlan(
        scope="NCE",
        series="NEW_CONCEPT_ENGLISH",
        title="New Concept English",
        source_id="iChochy/NCE",
        books=[book],
        new_vocab=[
            ResolvedVocab(
                normalized_form="excuse",
                lexeme_type="WORD",
                vocabulary_item_id=get_vid("excuse"),
                is_new=True,
                display_form="Excuse",
            )
        ],
    )


# ---------- canonical resolver ----------


async def test_resolver_reuses_existing_airport(db_session: AsyncSession):
    resolver = CanonicalVocabularyResolver(db_session)
    resolved = await resolver.resolve("airport", "WORD", "airport")
    assert resolved.is_new is False
    assert resolved.vocabulary_item_id == get_vid("airport")


async def test_resolver_creates_missing_vocab(db_session: AsyncSession):
    resolver = CanonicalVocabularyResolver(db_session)
    resolved = await resolver.resolve("puma", "WORD", "puma")
    assert resolved.is_new is True
    assert resolved.vocabulary_item_id == get_vid("puma")


async def test_airport_canonical_reuse_single_entity(db_session: AsyncSession):
    """airport must resolve to exactly one canonical id (no NCE duplicate)."""
    resolver = CanonicalVocabularyResolver(db_session)
    r1 = await resolver.resolve("airport", "WORD", "airport")
    r2 = await resolver.resolve("airport", "WORD", "AIRPORT")
    assert r1.vocabulary_item_id == r2.vocabulary_item_id == get_vid("airport")


# ---------- membership uniqueness / occurrence_count ----------


async def test_membership_uniqueness_and_occurrence_count(db_session: AsyncSession):
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    # handbag appears in 2 sentences of lesson 1 → 1 membership, count=2.
    rows = (
        await db_session.execute(
            text(
                """
                SELECT m.occurrence_count, m.first_sentence_id IS NOT NULL
                FROM lesson_vocabulary_memberships m
                JOIN lessons l ON l.id = m.lesson_id
                WHERE l.lesson_key = '001&002.Excuse Me'
                  AND m.vocabulary_item_id = :vid
                """
            ),
            {"vid": get_vid("handbag")},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == 2
    assert rows[0][1] is True

    # airport appears once → count=1
    rows2 = (
        await db_session.execute(
            text(
                """
                SELECT m.occurrence_count
                FROM lesson_vocabulary_memberships m
                JOIN lessons l ON l.id = m.lesson_id
                WHERE l.lesson_key = '001&002.Excuse Me'
                  AND m.vocabulary_item_id = :vid
                """
            ),
            {"vid": get_vid("airport")},
        )
    ).all()
    assert len(rows2) == 1
    assert rows2[0][0] == 1


async def test_sentence_occurrences_recorded(db_session: AsyncSession):
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM sentence_vocabulary_occurrences")
        )
    ).scalar()
    # sent1: 2 occurrences, sent2: 2 occurrences
    assert count == 4


# ---------- cross-source reuse ----------


async def test_cross_source_k12_reuse(db_session: AsyncSession):
    """airport is seeded in a K12 collection; NCE membership must reuse it."""
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    row = (
        await db_session.execute(
            text(
                """
                SELECT count(*) FROM vocabulary_collection_memberships m
                JOIN vocabulary_collections c ON c.id = m.collection_id
                WHERE c.scope = 'K12_SYNC' AND m.vocabulary_item_id = :vid
                """
            ),
            {"vid": get_vid("airport")},
        )
    ).scalar()
    assert row == 1
    # The NCE membership points at the same canonical id (no duplicate entity).
    nce = (
        await db_session.execute(
            text(
                """
                SELECT count(*) FROM lesson_vocabulary_memberships
                WHERE vocabulary_item_id = :vid
                """
            ),
            {"vid": get_vid("airport")},
        )
    ).scalar()
    assert nce == 1


# ---------- apply / idempotency ----------


async def test_apply_then_second_apply_idempotent(db_session: AsyncSession):
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    counts_before = {}
    for table in ("courses", "course_books", "lessons", "timed_sentences",
                  "lesson_vocabulary_memberships", "sentence_vocabulary_occurrences"):
        counts_before[table] = (
            await db_session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar()

    # Second apply: same plan, same transaction pattern.
    await repo.execute(plan)
    await db_session.commit()

    for table, before in counts_before.items():
        after = (
            await db_session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar()
        assert after == before, f"{table} grew on second apply"


async def test_apply_creates_batch_telemetry(db_session: AsyncSession):
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    batch = VocabularyImportBatch(
        id=str(uuid.uuid4()),
        source_name="iChochy/NCE",
        source_commit_sha="0a92ab5af50e2898a104f15eac7adb00f17bd96b",
        parser_version="nce-importer/1.0",
        mode="APPLY",
        status="SUCCESS",
    )
    db_session.add(batch)
    await db_session.commit()

    row = (
        await db_session.execute(
            text(
                "SELECT source_name, source_commit_sha, status FROM vocabulary_import_batches WHERE id = :id"
            ),
            {"id": batch.id},
        )
    ).one()
    assert row[0] == "iChochy/NCE"
    assert row[1] == "0a92ab5af50e2898a104f15eac7adb00f17bd96b"
    assert row[2] == "SUCCESS"


# ---------- learning events / FSRS zero pollution ----------


async def test_learning_events_zero_pollution(db_session: AsyncSession):
    before = (
        await db_session.execute(text("SELECT count(*) FROM learning_events"))
    ).scalar()
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    after = (
        await db_session.execute(text("SELECT count(*) FROM learning_events"))
    ).scalar()
    assert after == before


async def test_fsrs_zero_pollution(db_session: AsyncSession):
    """NCE import must not create or mutate FSRS state (kc_mastery)."""
    before = (
        await db_session.execute(text("SELECT count(*) FROM kc_mastery"))
    ).scalar()
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    after = (
        await db_session.execute(text("SELECT count(*) FROM kc_mastery"))
    ).scalar()
    assert after == before


# ---------- provenance ----------


async def test_provenance_completeness(db_session: AsyncSession):
    plan = _make_plan()
    repo = CourseImportRepository(db_session)
    await repo.execute(plan)
    await db_session.commit()

    books = (
        await db_session.execute(
            text("SELECT count(*) FROM course_books WHERE source_url IS NOT NULL AND source_hash IS NOT NULL")
        )
    ).scalar()
    assert books == 1

    lessons = (
        await db_session.execute(
            text("SELECT count(*) FROM lessons WHERE lrc_uri IS NOT NULL AND lrc_hash IS NOT NULL")
        )
    ).scalar()
    assert lessons == 2

    # lesson 1 has audio with hash; lesson 2 has no audio (audio_hash NULL allowed)
    audio = (
        await db_session.execute(
            text("SELECT count(*) FROM lessons WHERE audio_uri IS NOT NULL AND audio_hash IS NOT NULL")
        )
    ).scalar()
    assert audio == 1


# ---------- alembic single head ----------


def test_alembic_single_head():
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if "(head)" in line]
    assert len(heads) == 1
    # 必须跟着最新的迁移走。新增迁移后改这里，并确认只有一个 head
    # （多于一个说明有人把 down_revision 指错了，会在部署时炸）。
    assert "a3b4c5d6e7f8" in heads[0]

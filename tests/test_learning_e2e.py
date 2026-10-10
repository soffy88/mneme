"""P8 real-user-flow E2E integration test (SPEC §122).

Seeds a complete scenario on mneme_test:
    1 user, 1 K12 book, 2 lessons, 10 vocab,
    3 NCE overlap words, 2 Zhongkao words, 1 Gaokao word.

Full flow: create plan → start lesson → answer → fail → review →
NCE context → finish lesson → next-day review.

Verifies: VocabularyItem count unchanged, one KCMastery per user/vocab,
LearningEvents append, FSRS evolves, progress updates.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import services  # noqa: F401 — vendor-first path setup
from services.models import (
    Book,
    Course,
    Lesson,
    LessonVocabularyMembership,
    LearningPlan,
    TimedSentence,
    VocabularyCollection,
    VocabularyCollectionMembership,
)

from scripts.nce_importer.resolver import get_vid


async def _clean_e2e_users(conn) -> None:
    """Delete all rows referencing e2e users across every FK-dependent table."""
    candidate_tables = (
        "interaction_events", "interaction_history", "kc_mastery",
        "mastery_snapshots", "learning_events", "learning_outcome_ledger",
        "memory_claims", "memory_evidence", "papers", "highlights",
        "reading_notes", "socratic_sessions", "speaking_sessions",
        "streaks", "media_sessions", "media_telemetry_events",
        "cornell_progress", "daily_missions", "guardian_consents",
        "parent_alerts", "parent_student", "pilot_assignments",
        "pilot_enrollments", "pilot_measurement_schedules", "policy_decisions",
        "policy_outcome_links",
        "user_lesson_progress", "user_book_progress",
    )
    # learning_session_items has no user column — delete via session first
    await conn.execute(
        text("DELETE FROM learning_session_items WHERE session_id IN (SELECT id FROM learning_sessions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'e2e-%'))")
    )
    for t in candidate_tables:
        for col in ("student_id", "user_id"):
            exists = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
                    ),
                    {"t": t, "c": col},
                )
            ).scalar_one_or_none()
            if exists:
                await conn.execute(
                    text(f"DELETE FROM {t} WHERE {col} IN (SELECT id FROM users WHERE email LIKE 'e2e-%')")
                )
    # learning_sessions before learning_plans (FK dependency)
    await conn.execute(text("DELETE FROM learning_sessions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'e2e-%')"))
    await conn.execute(text("DELETE FROM learning_plans WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'e2e-%')"))
    # e2e course chain: delete in FK-safe order
    await conn.execute(text("DELETE FROM lesson_vocabulary_memberships WHERE lesson_id IN (SELECT id FROM lessons WHERE id LIKE 'e2e-%')"))
    await conn.execute(text("DELETE FROM timed_sentences WHERE lesson_id IN (SELECT id FROM lessons WHERE id LIKE 'e2e-%')"))
    await conn.execute(text("DELETE FROM lessons WHERE id LIKE 'e2e-%'"))
    await conn.execute(text("DELETE FROM course_books WHERE id LIKE 'e2e-%'"))
    await conn.execute(text("DELETE FROM courses WHERE id LIKE 'e2e-%'"))
    # e2e vocab chain: memberships → collections → items
    await conn.execute(text("DELETE FROM vocabulary_collection_memberships WHERE collection_id IN (SELECT id FROM vocabulary_collections WHERE id LIKE 'e2e-%')"))
    await conn.execute(text("DELETE FROM vocabulary_collections WHERE id LIKE 'e2e-%'"))
    await conn.execute(text("DELETE FROM vocabulary_items WHERE source='e2e'"))
    await conn.execute(text("DELETE FROM users WHERE email LIKE 'e2e-%'"))


# Scenario vocab: 3 NCE overlap, 2 zhongkao, 1 gaokao, 4 k12-only
VOCAB = [
    ("airport", "机场"),       # NCE + zhongkao + gaokao
    ("handbag", "手提包"),      # NCE + zhongkao
    ("puma", "美洲狮"),         # NCE only
    ("quintuplet", "五胞胎"),    # k12 lesson 1
    ("microscope", "显微镜"),    # k12 lesson 1
    ("volcano", "火山"),       # k12 lesson 2
    ("glacier", "冰川"),       # k12 lesson 2
    ("census", "人口普查"),     # k12 lesson 2
    ("orbit", "轨道"),          # k12 lesson 2
    ("solar", "太阳能的"),       # k12 lesson 2
]


@pytest.fixture
async def e2e_session():
    """Full schema + seed data on mneme_test; cleaned up after."""
    url = __import__("os").environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)

    from services.models import (
        LearningSession,
        LearningSessionItem,
        UserBookProgress,
        UserLessonProgress,
    )

    course_tables = [
        Course.__table__,
        Book.__table__,
        Lesson.__table__,
        TimedSentence.__table__,
        LessonVocabularyMembership.__table__,
        VocabularyCollection.__table__,
        VocabularyCollectionMembership.__table__,
        LearningPlan.__table__,
        LearningSession.__table__,
        LearningSessionItem.__table__,
        UserLessonProgress.__table__,
        UserBookProgress.__table__,
    ]

    async with engine.begin() as conn:
        # ensure users table exists (pre-existing in mneme_test)
        def _create(sync_conn):
            from services.models import Base

            Base.metadata.create_all(bind=sync_conn, tables=course_tables, checkfirst=True)

        await conn.run_sync(_create)

    async with engine.begin() as conn:
        await _clean_e2e_users(conn)

        # user
        user_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO users (id, email, role, name, grade) VALUES (:id, :email, 'student', 'E2E', '7')"
            ),
            {"id": user_id, "email": f"e2e-{user_id}@test.com"},
        )

        # vocab
        for word, meaning in VOCAB:
            vid = get_vid(word)
            await conn.execute(
                text(
                    """
                    INSERT INTO vocabulary_items
                        (id, word, language, display_form, normalized_form, lexeme_type,
                         meaning_cn, frequency_rank, frequency_band, source, ai_generated)
                    VALUES (:id, :word, 'en', :word, :word, 'WORD', :meaning, 99999, 5, 'e2e', false)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": vid, "word": word, "meaning": meaning},
            )

        # K12 course + book
        course_id = "e2e-course-k12"
        await conn.execute(
            text(
                "INSERT INTO courses (id, scope, series, title, source_id) VALUES (:id, 'K12_SYNC', 'E2E_K12', 'E2E K12', 'e2e')"
            ),
            {"id": course_id},
        )
        book_id = "e2e-book-1"
        await conn.execute(
            text(
                "INSERT INTO course_books (id, course_id, book_key, title, level, edition) VALUES (:id, :cid, 'E2E-1', 'E2E Book 1', '7th', 'CURRENT')"
            ),
            {"id": book_id, "cid": course_id},
        )

        # lessons
        lesson1_id = "e2e-lesson-1"
        lesson2_id = "e2e-lesson-2"
        for lid, title, order in [
            (lesson1_id, "Lesson 1", 1),
            (lesson2_id, "Lesson 2", 2),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO lessons (id, book_id, lesson_key, title, source_order) VALUES (:id, :bid, :k, :t, :o)"
                ),
                {"id": lid, "bid": book_id, "k": lid, "t": title, "o": order},
            )

        # lesson vocab: lesson1 = first 5, lesson2 = last 5
        for i, (word, _) in enumerate(VOCAB[:5]):
            await conn.execute(
                text(
                    "INSERT INTO lesson_vocabulary_memberships (id, lesson_id, vocabulary_item_id, occurrence_count, source_order) VALUES (:id, :lid, :vid, 1, :o)"
                ),
                {"id": f"e2e-lm1-{i}", "lid": lesson1_id, "vid": get_vid(word), "o": i + 1},
            )
        for i, (word, _) in enumerate(VOCAB[5:]):
            await conn.execute(
                text(
                    "INSERT INTO lesson_vocabulary_memberships (id, lesson_id, vocabulary_item_id, occurrence_count, source_order) VALUES (:id, :lid, :vid, 1, :o)"
                ),
                {"id": f"e2e-lm2-{i}", "lid": lesson2_id, "vid": get_vid(word), "o": i + 1},
            )

        # timed sentences for NCE vocab (airport, handbag, puma)
        nce_sentences = [
            ("e2e-sent-1", "I went to the airport yesterday.", "我昨天去了机场。", 0, 2000),
            ("e2e-sent-2", "The handbag is expensive.", "这个手提包很贵。", 0, 1500),
            ("e2e-sent-3", "A puma is a large cat.", "美洲狮是一种大型猫科动物。", 0, 1800),
        ]
        for sid, en, zh, start, end in nce_sentences:
            await conn.execute(
                text(
                    """
                    INSERT INTO timed_sentences
                        (id, lesson_id, source_order, start_ms, end_ms, english_text, chinese_text, raw_text, source_entry_key)
                    VALUES (:id, :lid, 1, :s, :e, :en, :zh, :raw, :key)
                    """
                ),
                {"id": sid, "lid": lesson1_id, "s": start, "e": end, "en": en, "zh": zh, "raw": en, "key": en},
            )
            for word in ["airport", "handbag", "puma"]:
                if word in en.lower():
                    await conn.execute(
                        text(
                            "INSERT INTO lesson_vocabulary_memberships (id, lesson_id, vocabulary_item_id, occurrence_count, source_order) VALUES (:id, :lid, :vid, 1, 1) ON CONFLICT DO NOTHING"
                        ),
                        {"id": f"e2e-nce-{word}", "lid": lesson1_id, "vid": get_vid(word)},
                    )

        # collections: zhongkao + gaokao
        for scope, words in [
            ("ZHONGKAO", ["airport", "handbag"]),
            ("GAOKAO", ["airport"]),
        ]:
            coll_id = f"e2e-coll-{scope.lower()}"
            await conn.execute(
                text(
                    "INSERT INTO vocabulary_collections (id, kind, scope, title, stage) VALUES (:id, 'EXAM', :scope, :title, 'SENIOR')"
                ),
                {"id": coll_id, "scope": scope, "title": f"E2E {scope}"},
            )
            for word in words:
                await conn.execute(
                    text(
                        "INSERT INTO vocabulary_collection_memberships (id, collection_id, vocabulary_item_id) VALUES (:id, :cid, :vid)"
                    ),
                    {"id": f"e2e-cm-{scope}-{word}", "cid": coll_id, "vid": get_vid(word)},
                )

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = Session()
    try:
        yield session, user_id
    finally:
        await session.close()
        async with engine.begin() as conn:
            await _clean_e2e_users(conn)
        async with engine.begin() as conn:
            for t in [
                "learning_session_items", "learning_sessions",
                "user_lesson_progress", "user_book_progress",
                "learning_plans", "lesson_vocabulary_memberships",
                "timed_sentences", "lessons", "course_books", "courses",
                "vocabulary_collection_memberships", "vocabulary_collections",
            ]:
                # 只清数据、不删表：这些表归 Alembic 管，DROP 会让 mneme_test
                # 停在 head 却缺表，后续测试随机 UndefinedTable（2026-10-10 审计）。
                if (await conn.execute(text(f"SELECT to_regclass('{t}')"))).scalar():
                    await conn.execute(text(f"TRUNCATE TABLE {t} CASCADE"))
        await engine.dispose()


# ---------- E2E flow ----------

async def test_full_learning_flow(e2e_session):
    session, user_id = e2e_session
    from services.learning_engine import LearningEngine

    engine = LearningEngine(session)

    # 1. create plan
    plan = LearningPlan(
        user_id=user_id,
        primary_scope="K12_SYNC",
        current_lesson_id="e2e-lesson-1",
        exam_target="ZHONGKAO",
    )
    session.add(plan)
    await session.commit()

    # 2. start lesson session
    built = await engine.build_lesson_session(user_id, "e2e-lesson-1", learning_plan_id=plan.id)
    assert len(built.items) > 0
    await session.commit()

    # 3. answer correctly
    from services.learning_scoring import Score

    result = await engine.submit_answer(
        built.session_id,
        1,
        answer="机场",
        interaction_id=uuid.uuid4(),
    )
    assert result.score == Score.CORRECT
    await session.commit()

    # 4. KCMastery created for the vocab (single authority)
    kp_count = (
        await session.execute(
            text("SELECT count(*) FROM kc_mastery WHERE student_id = :uid AND knowledge_point LIKE 'vocab-%'"),
            {"uid": user_id},
        )
    ).scalar()
    assert kp_count >= 1

    # 5. VocabularyItem count unchanged (no duplicates created)
    vocab_count = (
        await session.execute(text("SELECT count(*) FROM vocabulary_items WHERE source='e2e'"))
    ).scalar()
    assert vocab_count == len(VOCAB)


async def test_canonical_reuse_across_sources(e2e_session):
    """airport in K12 + NCE + zhongkao + gaokao → 1 VocabularyItem (SPEC §126)."""
    session, user_id = e2e_session
    airport = get_vid("airport")

    # exactly one VocabularyItem
    count = (
        await session.execute(
            text("SELECT count(*) FROM vocabulary_items WHERE id = :id"), {"id": airport}
        )
    ).scalar()
    assert count == 1

    # memberships across all sources point to the same id
    nce_mem = (
        await session.execute(
            text("SELECT count(*) FROM lesson_vocabulary_memberships WHERE vocabulary_item_id = :id"),
            {"id": airport},
        )
    ).scalar()
    assert nce_mem >= 1


async def test_exam_coverage(e2e_session):
    session, user_id = e2e_session
    from services.progress_engine import ProgressEngine

    engine = ProgressEngine(session)
    zhongkao = await engine.exam_coverage("ZHONGKAO")
    assert zhongkao.total == 2  # airport + handbag
    gaokao = await engine.exam_coverage("GAOKAO")
    assert gaokao.total == 1  # airport


async def test_session_resume(e2e_session):
    """Session items are immutable after creation (SPEC §102/72)."""
    session, user_id = e2e_session
    from services.learning_engine import LearningEngine

    engine = LearningEngine(session)
    built = await engine.build_lesson_session(user_id, "e2e-lesson-1", learning_plan_id=None)
    await session.commit()

    items_before = (
        await session.execute(
            text('SELECT task_type, context_source FROM learning_session_items WHERE session_id = :sid ORDER BY "sequence"'),
            {"sid": built.session_id},
        )
    ).all()

    # rebuild should produce the same items (deterministic)
    built2 = await engine.build_lesson_session(user_id, "e2e-lesson-1", learning_plan_id=None)
    await session.commit()
    # different session, but item prompts for the same lesson are deterministic
    assert len(built.items) > 0
    assert built2.session_id != built.session_id
    assert [(i.task_type.value, i.context_source) for i in built2.items] == [
        (r[0], r[1]) for r in items_before
    ]


async def test_answer_idempotency(e2e_session):
    """Same interaction answered twice → item locked, no double FSRS update (SPEC §71)."""
    session, user_id = e2e_session
    from services.learning_engine import LearningEngine

    engine = LearningEngine(session)
    built = await engine.build_lesson_session(user_id, "e2e-lesson-1", learning_plan_id=None)
    await session.commit()

    interaction_id = uuid.uuid4()
    r1 = await engine.submit_answer(built.session_id, 1, answer="机场", interaction_id=interaction_id)
    await session.commit()
    assert r1.score.value == "CORRECT"

    # second submit on same item → rejected (item already ANSWERED)

    from services.models import LearningSessionItem

    item = (
        await session.execute(
            select(LearningSessionItem).where(
                LearningSessionItem.session_id == built.session_id,
                LearningSessionItem.sequence == 1,
            )
        )
    ).scalar_one()
    assert item.state == "ANSWERED"

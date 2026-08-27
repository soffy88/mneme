"""RC1 P0 hotfix regression tests against the real PostgreSQL test database."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from obase.config import settings
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from event_schema import EventOutcome, LearningEvent
from services.cognitive_service import process_interaction
from services.learning_event_replay_service import ReplayConfig, replay_events
from services.models import (
    InteractionEvent,
    KCMastery,
    MemoryClaim,
    MemoryClaimEvidence,
    MemoryEvidence,
    PilotAssignment,
    PilotEnrollment,
    PilotMeasurementSchedule,
    User,
    UserRole,
)
from services.purge_service import (
    PurgeStorageCleanupError,
    _table_exists,
    purge_deleted_users,
    verify_student_purge,
)


@pytest.fixture
async def db_factory():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db, factory
    await engine.dispose()


async def _new_student(db: AsyncSession, *, deleted: bool = False) -> UUID:
    sid = uuid4()
    db.add(
        User(
            id=sid,
            phone=f"{sid.int % 10**10:010d}",
            role=UserRole.student,
            deleted_at=(datetime.now(UTC) - timedelta(days=40)) if deleted else None,
        )
    )
    await db.flush()
    return sid


async def _cleanup_student(db: AsyncSession, sid: UUID) -> None:
    """Remove only this test learner, respecting the live FK order."""
    if await _table_exists(db, "memory_claim_evidence"):
        await db.execute(
            text(
                "DELETE FROM memory_claim_evidence WHERE claim_id IN "
                "(SELECT id FROM memory_claims WHERE student_id=:sid) "
                "OR evidence_id IN (SELECT id FROM memory_evidence WHERE student_id=:sid)"
            ),
            {"sid": str(sid)},
        )
    for table, column in (
        ("pilot_assignments", "student_id"),
        ("pilot_measurement_schedules", "student_id"),
        ("pilot_enrollments", "student_id"),
        ("effortful_gains", "student_id"),
        ("mastery_snapshots", "student_id"),
        ("interaction_events", "student_id"),
        ("learning_events", "student_id"),
        ("memory_claims", "student_id"),
        ("memory_evidence", "student_id"),
        ("kc_mastery", "student_id"),
    ):
        if await _table_exists(db, table):
            await db.execute(
                text(f"DELETE FROM {table} WHERE {column}=:sid"),
                {"sid": str(sid)},
            )
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


async def _seed_pilot_graph(db: AsyncSession, sid: UUID) -> UUID:
    now = datetime.now(UTC)
    enrollment_id = uuid4()
    protocol_id = f"rc1-p0-{uuid4().hex[:12]}"
    db.add(
        PilotEnrollment(
            enrollment_id=enrollment_id,
            student_id=sid,
            protocol_id=protocol_id,
            protocol_version="1",
            cohort_id="hotfix",
            consent_status="PENDING",
            enrolled_at=now - timedelta(days=40),
        )
    )
    await db.flush()
    db.add(
        PilotAssignment(
            enrollment_id=enrollment_id,
            student_id=sid,
            protocol_id=protocol_id,
            protocol_version="1",
            cohort_id="hotfix",
            arm="control",
            assignment_method="deterministic",
            assigned_at=now - timedelta(days=40),
        )
    )
    db.add(
        PilotMeasurementSchedule(
            student_id=sid,
            enrollment_id=enrollment_id,
            protocol_id=protocol_id,
            protocol_version="1",
            phase="baseline",
            measurement_due_at=now,
            window_open_at=now,
            window_close_at=now + timedelta(days=1),
        )
    )
    await db.flush()
    return enrollment_id


@pytest.mark.asyncio
async def test_review_advances_fsrs_schedule(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P01", True, source="quick", now=t0)
        await db.commit()
        before = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P01"
                )
            )
        ).scalar_one()
        card_before = copy.deepcopy(before.fsrs_card_json)
        await process_interaction(
            db,
            sid,
            "RC1P01",
            True,
            source="review",
            now=t0 + timedelta(hours=2),
        )
        await db.commit()
        after = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P01"
                )
            )
        ).scalar_one()
        assert after.p_mastery != pytest.approx(0.6756756757)
        assert after.fsrs_card_json["due"] != card_before["due"]
        assert after.fsrs_card_json["last_review"] != card_before["last_review"]
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_review_updates_mastery_and_fsrs(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P02", True, source="quick", now=t0)
        await db.commit()
        before = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P02"
                )
            )
        ).scalar_one()
        p_before = before.p_mastery
        card_before = copy.deepcopy(before.fsrs_card_json)
        await process_interaction(
            db, sid, "RC1P02", True, source="review", now=t0 + timedelta(hours=2)
        )
        await db.commit()
        after = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P02"
                )
            )
        ).scalar_one()
        assert after.p_mastery > p_before
        assert after.fsrs_card_json["last_review"] != card_before["last_review"]
        event = (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        ).scalars().first()
        assert event is not None
        assert event.source.value == "review"
        assert event.fsrs_rating == 3
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_incorrect_review_updates_fsrs(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P03", True, source="quick", now=t0)
        await db.commit()
        before = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P03"
                )
            )
        ).scalar_one()
        await process_interaction(
            db, sid, "RC1P03", False, source="review", now=t0 + timedelta(hours=2)
        )
        await db.commit()
        after = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P03"
                )
            )
        ).scalar_one()
        assert after["last_review"] != before["last_review"]
        event = (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        ).scalars().first()
        assert event is not None
        assert event.is_correct is False
        assert event.fsrs_rating == 1
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_duplicate_review_does_not_double_schedule(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P04", True, source="quick", now=t0)
        await db.commit()
        review_at = t0 + timedelta(hours=2)
        await process_interaction(db, sid, "RC1P04", True, source="review", now=review_at)
        await db.commit()
        first = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P04"
                )
            )
        ).scalar_one()
        await process_interaction(
            db, sid, "RC1P04", True, source="review", now=review_at + timedelta(minutes=1)
        )
        await db.commit()
        second = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P04"
                )
            )
        ).scalar_one()
        assert second == first
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_duplicate_event_id_does_not_double_schedule(db_factory):
    """The same immutable event identity applies BKT/FSRS exactly once."""
    db, _factory = db_factory
    sid = await _new_student(db)
    first_event_id, review_event_id = uuid4(), uuid4()
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(
            db,
            sid,
            "RC1P04_EVENT_ID",
            True,
            source="quick",
            event_id=first_event_id,
            now=t0,
        )
        await db.commit()
        await process_interaction(
            db,
            sid,
            "RC1P04_EVENT_ID",
            True,
            source="review",
            event_id=review_event_id,
            now=t0 + timedelta(hours=2),
        )
        await db.commit()
        first = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid,
                    KCMastery.knowledge_point == "RC1P04_EVENT_ID",
                )
            )
        ).scalar_one()
        card_after_first = copy.deepcopy(first.fsrs_card_json)
        attempts_after_first = first.n_attempts

        duplicate = await process_interaction(
            db,
            sid,
            "RC1P04_EVENT_ID",
            True,
            source="review",
            event_id=review_event_id,
            now=t0 + timedelta(hours=2, minutes=1),
        )
        await db.commit()
        second = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == sid,
                    KCMastery.knowledge_point == "RC1P04_EVENT_ID",
                )
            )
        ).scalar_one()
        assert duplicate["duplicate"] is True
        assert second.n_attempts == attempts_after_first
        assert second.fsrs_card_json == card_after_first
        assert (
            await db.execute(
                text(
                    "SELECT count(*) FROM interaction_events "
                    "WHERE student_id=:sid AND id=:event_id"
                ),
                {"sid": str(sid), "event_id": str(review_event_id)},
            )
        ).scalar_one() == 1
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_replay_reproduces_fsrs_schedule(db_factory):
    _db, _factory = db_factory
    sid = uuid4()
    base = datetime(2026, 8, 24, 12, tzinfo=UTC)

    def event(event_id: str, at: datetime, source: str, correct: bool) -> LearningEvent:
        return LearningEvent(
            event_id=UUID(event_id),
            actor_id=sid,
            student_id=sid,
            occurred_at=at,
            received_at=at,
            source=source,
            action="attempted",
            object_type="question",
            object_id="question-1",
            knowledge_refs=["RC1P05"],
            outcome=EventOutcome(correctness=correct, fsrs_rating=3 if correct else 1),
        )

    events = [
        event("00000000-0000-0000-0000-000000000101", base, "quick", True),
        event("00000000-0000-0000-0000-000000000102", base + timedelta(hours=2), "review", True),
    ]
    config = ReplayConfig(min_review_interval_hours=20.0)
    first = await replay_events(events, student_id=sid, config=config, computed_at=base)
    second = await replay_events(list(reversed(events)), student_id=sid, config=config, computed_at=base)
    assert first.states == second.states
    assert first.states["RC1P05"]["fsrs_card"]["last_review"] == events[-1].occurred_at.isoformat()


@pytest.mark.asyncio
async def test_ineligible_event_does_not_advance_fsrs(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P06", True, source="quick", now=t0)
        await db.commit()
        before = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P06"
                )
            )
        ).scalar_one()
        await process_interaction(
            db, sid, "RC1P06", True, source="review", now=t0 + timedelta(minutes=1)
        )
        await db.commit()
        after = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P06"
                )
            )
        ).scalar_one()
        assert after == before
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_review_next_review_persists_after_restart(db_factory):
    db, factory = db_factory
    sid = await _new_student(db)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    try:
        await process_interaction(db, sid, "RC1P07", True, source="quick", now=t0)
        await db.commit()
        await process_interaction(
            db, sid, "RC1P07", True, source="review", now=t0 + timedelta(hours=2)
        )
        await db.commit()
        expected = (
            await db.execute(
                select(KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P07"
                )
            )
        ).scalar_one()
        async with factory() as restarted:
            actual = (
                await restarted.execute(
                    select(KCMastery.fsrs_card_json).where(
                        KCMastery.student_id == sid, KCMastery.knowledge_point == "RC1P07"
                    )
                )
            ).scalar_one()
        assert actual["due"] == expected["due"]
        assert actual["last_review"] == expected["last_review"]
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_pilot_assignment_before_enrollment(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    try:
        await _seed_pilot_graph(db, sid)
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert result["purge_complete"] is True
        assert await verify_student_purge(db, sid) == {}
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_with_full_pilot_graph(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    try:
        await _seed_pilot_graph(db, sid)
        await process_interaction(db, sid, "RC1P08", False, source="review")
        await db.commit()
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert result["purge_complete"] is True
        assert await verify_student_purge(db, sid) == {}
        for table in (
            "pilot_enrollments",
            "pilot_assignments",
            "pilot_measurement_schedules",
            "interaction_events",
            "learning_events",
            "kc_mastery",
        ):
            if await _table_exists(db, table):
                assert (
                    await db.execute(
                        text(f"SELECT count(*) FROM {table} WHERE student_id=:sid"),
                        {"sid": str(sid)},
                    )
                ).scalar_one() == 0
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_is_atomic_on_fk_failure(db_factory, monkeypatch):
    """The old dependency order fails closed without committing partial deletes."""
    import services.purge_service as purge_module

    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    await _seed_pilot_graph(db, sid)
    await db.commit()
    original = purge_module._STUDENT_TABLES
    monkeypatch.setattr(
        purge_module,
        "_STUDENT_TABLES",
        [("pilot_enrollments", "student_id"), ("pilot_assignments", "student_id")],
    )
    try:
        with pytest.raises(IntegrityError):
            await purge_deleted_users(db, grace_days=30)
        await db.rollback()
        assert (
            await db.execute(text("SELECT count(*) FROM pilot_enrollments WHERE student_id=:sid"), {"sid": str(sid)})
        ).scalar_one() == 1
        assert (
            await db.execute(text("SELECT count(*) FROM pilot_assignments WHERE student_id=:sid"), {"sid": str(sid)})
        ).scalar_one() == 1
        assert (await db.execute(select(User).where(User.id == sid))).scalar_one_or_none() is not None
    finally:
        monkeypatch.setattr(purge_module, "_STUDENT_TABLES", original)
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_verifies_no_student_residuals(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    try:
        await _seed_pilot_graph(db, sid)
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert result["purge_complete"] is True
        assert result["storage_cleanup_pending"] == []
        assert await verify_student_purge(db, sid) == {}
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_is_idempotent_after_success(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    try:
        await _seed_pilot_graph(db, sid)
        first = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        second = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert first["purge_complete"] is True
        assert second == {
            "purged_users": 0,
            "ids": [],
            "tables": {},
            "storage_cleanup_pending": [],
            "purge_complete": True,
        }
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_storage_failure_rolls_back_and_is_explicit(db_factory, monkeypatch):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    try:
        await _seed_pilot_graph(db, sid)
        await db.commit()

        async def failed_cleanup():
            return ["staging/test-object"]

        import services.purge_service as purge_module

        monkeypatch.setattr(purge_module, "_delete_textbook_files_blobs", failed_cleanup)
        with pytest.raises(PurgeStorageCleanupError) as exc_info:
            await purge_deleted_users(db, grace_days=30)
        await db.rollback()
        assert exc_info.value.paths == ("staging/test-object",)
        assert (
            await db.execute(
                text("SELECT count(*) FROM users WHERE id=:sid"),
                {"sid": str(sid)},
            )
        ).scalar_one() == 1
        assert await verify_student_purge(db, sid) == {
            "pilot_assignments.student_id": 1,
            "pilot_measurement_schedules.student_id": 1,
            "pilot_enrollments.student_id": 1,
            "users.id": 1,
        }
    finally:
        await _cleanup_student(db, sid)


@pytest.mark.asyncio
async def test_purge_b_preserves_other_user_data(db_factory):
    db, _factory = db_factory
    user_a = await _new_student(db)
    user_b = await _new_student(db, deleted=True)
    try:
        await process_interaction(db, user_a, "RC1P10", True, source="quick")
        await db.commit()
        a_before = (
            await db.execute(
                select(KCMastery.p_mastery, KCMastery.n_attempts).where(
                    KCMastery.student_id == user_a,
                    KCMastery.knowledge_point == "RC1P10",
                )
            )
        ).one()
        await _seed_pilot_graph(db, user_b)
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert result["purge_complete"] is True
        a_after = (
            await db.execute(
                select(KCMastery.p_mastery, KCMastery.n_attempts).where(
                    KCMastery.student_id == user_a,
                    KCMastery.knowledge_point == "RC1P10",
                )
            )
        ).one()
        assert a_after == a_before
        assert await verify_student_purge(db, user_b) == {}
    finally:
        await _cleanup_student(db, user_a)
        await _cleanup_student(db, user_b)


@pytest.mark.asyncio
async def test_purge_evidence(db_factory):
    db, _factory = db_factory
    sid = await _new_student(db, deleted=True)
    now = datetime.now(UTC)
    claim_id, evidence_id = uuid4(), uuid4()
    try:
        db.add(
            MemoryClaim(
                id=claim_id,
                student_id=sid,
                claim_type="mastery",
                subject_type="knowledge_point",
                subject_id="RC1P09",
                claim_text="test claim",
                evidence_level="contract",
                privacy_class="P1",
                provenance={},
            )
        )
        db.add(
            MemoryEvidence(
                id=evidence_id,
                student_id=sid,
                evidence_type="interaction",
                occurred_at=now,
                evidence_level="contract",
                payload={},
                provenance={},
            )
        )
        await db.flush()
        db.add(MemoryClaimEvidence(claim_id=claim_id, evidence_id=evidence_id, relation="supports"))
        await db.flush()
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert result["purge_complete"] is True
        assert await verify_student_purge(db, sid) == {}
    finally:
        await _cleanup_student(db, sid)

"""Run the two RC1 P0 regressions against the running staging PostgreSQL.

This is intentionally a production-service path, not a test double.  Run it
inside the staging API image after a release update, for example:

    python scripts/rc1_p0_staging_regression.py --expected-sha <rc2-sha>

Only short-lived synthetic learner data and one synthetic MinIO object are
created; the script removes them before exiting.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
for entry in (
    ROOT,
    ROOT / "packages" / "event-schema",
    ROOT / "packages" / "mneme-agent",
    ROOT / "packages" / "mneme-core",
    ROOT / "vendor",
):
    value = str(entry)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)

from sqlalchemy import delete, select, text

from obase.db import SessionLocal
from services.cognitive_service import process_interaction
from services.models import (
    InteractionEvent,
    KCMastery,
    MemoryClaim,
    MemoryClaimEvidence,
    MemoryEvidence,
    PilotAssignment,
    PilotEnrollment,
    PilotMeasurementSchedule,
    TextbookFile,
    User,
    UserRole,
)
from services.purge_service import purge_deleted_users, verify_student_purge
from services.storage import delete_file, download_file, upload_file


async def _cleanup_student(db, student_id: UUID, object_path: str | None = None) -> None:
    if object_path:
        try:
            delete_file(object_path)
        except Exception:
            pass
    if await _exists(db, "memory_claim_evidence"):
        await db.execute(
            text(
                "DELETE FROM memory_claim_evidence WHERE claim_id IN "
                "(SELECT id FROM memory_claims WHERE student_id=:sid) OR "
                "evidence_id IN (SELECT id FROM memory_evidence WHERE student_id=:sid)"
            ),
            {"sid": str(student_id)},
        )
    for table, column in (
        ("pilot_assignments", "student_id"),
        ("pilot_measurement_schedules", "student_id"),
        ("pilot_enrollments", "student_id"),
        ("interaction_events", "student_id"),
        ("learning_events", "student_id"),
        ("memory_claims", "student_id"),
        ("memory_evidence", "student_id"),
        ("kc_mastery", "student_id"),
        ("textbook_files", "owner_student_id"),
    ):
        if await _exists(db, table):
            await db.execute(
                text(f"DELETE FROM {table} WHERE {column}=:sid"),
                {"sid": str(student_id)},
            )
    await db.execute(delete(User).where(User.id == student_id))
    await db.commit()


async def _exists(db, table: str) -> bool:
    return (await db.execute(text("SELECT to_regclass(:table)"), {"table": table})).scalar() is not None


async def _run(expected_sha: str) -> dict:
    actual_sha = os.environ.get("GIT_SHA") or os.environ.get("MNEME_CODE_SHA") or ""
    if expected_sha and actual_sha and actual_sha != expected_sha:
        raise RuntimeError(f"staging release identity mismatch: {actual_sha}")

    result: dict = {"environment": os.environ.get("MNEME_ENV", ""), "release_sha": actual_sha}
    sid = uuid4()
    kc_id = f"rc1-p0-1-{sid.hex[:10]}"
    object_path = f"rc1-p0/{sid}.bin"
    first_event_id = uuid4()
    review_event_id = uuid4()
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    t1 = t0 + timedelta(hours=2)

    async with SessionLocal() as db:
        try:
            db.add(User(id=sid, phone=f"{sid.int % 10**10:010d}", role=UserRole.student))
            await db.commit()
            await process_interaction(
                db,
                sid,
                kc_id,
                True,
                source="quick",
                event_id=first_event_id,
                now=t0,
            )
            await db.commit()
            before = (
                await db.execute(
                    select(KCMastery).where(
                        KCMastery.student_id == sid,
                        KCMastery.knowledge_point == kc_id,
                    )
                )
            ).scalar_one()
            card_before = copy.deepcopy(before.fsrs_card_json)
            await process_interaction(
                db,
                sid,
                kc_id,
                True,
                source="review",
                event_id=review_event_id,
                now=t1,
            )
            await db.commit()
            after = (
                await db.execute(
                    select(KCMastery).where(
                        KCMastery.student_id == sid,
                        KCMastery.knowledge_point == kc_id,
                    )
                )
            ).scalar_one()
            event = (
                await db.execute(
                    select(InteractionEvent)
                    .where(InteractionEvent.student_id == sid)
                    .order_by(InteractionEvent.occurred_at.desc())
                )
            ).scalars().first()
            result["p0_1"] = {
                "student_id": str(sid),
                "event_id": str(event.id) if event else None,
                "mastery_before": before.p_mastery,
                "mastery_after": after.p_mastery,
                "fsrs_before": {k: card_before.get(k) for k in ("stability", "difficulty", "due", "last_review")},
                "fsrs_after": {k: after.fsrs_card_json.get(k) for k in ("stability", "difficulty", "due", "last_review")},
            }
            if card_before["due"] == after.fsrs_card_json["due"]:
                raise AssertionError("review did not advance FSRS due")
            if card_before["last_review"] == after.fsrs_card_json["last_review"]:
                raise AssertionError("review did not persist FSRS last_review")
            if after.p_mastery == before.p_mastery:
                raise AssertionError("review did not update mastery")

            card_after_review = copy.deepcopy(after.fsrs_card_json)
            attempts_after_review = after.n_attempts
            duplicate = await process_interaction(
                db,
                sid,
                kc_id,
                True,
                source="review",
                event_id=review_event_id,
                now=t1 + timedelta(minutes=1),
            )
            await db.flush()
            duplicate_row = (
                await db.execute(
                    select(KCMastery).where(
                        KCMastery.student_id == sid,
                        KCMastery.knowledge_point == kc_id,
                    )
                )
            ).scalar_one()
            if not duplicate.get("duplicate"):
                raise AssertionError("duplicate review was not identified")
            if duplicate_row.n_attempts != attempts_after_review:
                raise AssertionError("duplicate review changed mastery attempts")
            if duplicate_row.fsrs_card_json != card_after_review:
                raise AssertionError("duplicate review double-advanced FSRS")
            result["p0_1"]["duplicate"] = {
                "duplicate": True,
                "attempts_unchanged": True,
                "schedule_unchanged": True,
            }

            await _cleanup_student(db, sid)

            sid = uuid4()
            enrollment_id = uuid4()
            now = datetime.now(UTC)
            protocol_id = f"rc1-p0-2-{sid.hex[:10]}"
            db.add(
                User(
                    id=sid,
                    phone=f"{sid.int % 10**10:010d}",
                    role=UserRole.student,
                    deleted_at=now - timedelta(days=40),
                )
            )
            await db.flush()
            db.add(
                PilotEnrollment(
                    enrollment_id=enrollment_id,
                    student_id=sid,
                    protocol_id=protocol_id,
                    protocol_version="1",
                    cohort_id="staging-hotfix",
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
                    cohort_id="staging-hotfix",
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
            claim_id, evidence_id = uuid4(), uuid4()
            db.add(
                MemoryClaim(
                    id=claim_id,
                    student_id=sid,
                    claim_type="mastery",
                    subject_type="knowledge_point",
                    subject_id=kc_id,
                    claim_text="synthetic staging regression claim",
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
            upload_file(object_path, b"synthetic RC1 P0 staging object", "application/octet-stream")
            db.add(
                TextbookFile(
                    id=f"rc1-{sid.hex[:12]}",
                    owner_student_id=sid,
                    filename="synthetic.bin",
                    file_type="pdf",
                    storage_path=object_path,
                )
            )
            await db.flush()
            db.add(MemoryClaimEvidence(claim_id=claim_id, evidence_id=evidence_id, relation="supports"))
            await db.commit()

            purge_result = await purge_deleted_users(db, grace_days=30)
            await db.commit()
            if str(sid) not in purge_result["ids"] or not purge_result["purge_complete"]:
                raise AssertionError(f"purge incomplete: {purge_result}")
            residual = await verify_student_purge(db, sid)
            if residual:
                raise AssertionError(f"purge residuals: {residual}")
            try:
                download_file(object_path)
            except FileNotFoundError:
                object_residual = False
            else:
                object_residual = True
            if object_residual:
                raise AssertionError("purge left the synthetic object")
            result["p0_2"] = {
                "student_id": str(sid),
                "enrollment_id": str(enrollment_id),
                "purge_result": purge_result,
                "db_residual": residual,
                "object_residual": object_residual,
                "idempotent": (await purge_deleted_users(db, grace_days=30))["purged_users"] == 0,
            }
            await db.commit()
            return result
        finally:
            await db.rollback()
            await _cleanup_student(db, sid, object_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", default="")
    args = parser.parse_args()
    import asyncio

    result = asyncio.run(_run(args.expected_sha))
    print(result)


if __name__ == "__main__":
    main()

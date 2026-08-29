"""Live Immersive golden path against mneme_test (service layer, no prod API).

Uses async DB + patched local blob storage. Avoids TestClient lifespan/PgPool
conflicts while still exercising upload→transcript→session→telemetry→practice
→transfer→delete→IDOR on the real immersive stack.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from obase.config import settings
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from services.feature_flags import immersive_learning_enabled
from services.immersive.media_service import (
    append_telemetry,
    attach_transcript,
    create_media_from_upload,
    get_owned_media,
    start_or_resume_session,
)
from services.immersive.practice import run_dictation, run_listening, run_transfer
from services.models import MediaAsset, User, UserRole
from services.purge_service import delete_media_asset


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
def blob_patches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "blobs"
    root.mkdir()

    def _path(object_path: str) -> Path:
        target = root / object_path.lstrip("/").replace("..", "_")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def upload_media_file(object_path: str, data: bytes, content_type: str) -> None:
        _path(object_path).write_bytes(data)

    def delete_media_file(object_path: str) -> None:
        _path(object_path).unlink(missing_ok=True)

    monkeypatch.setattr(
        "services.immersive.media_service.upload_media_file", upload_media_file
    )
    monkeypatch.setattr("services.storage.delete_media_file", delete_media_file)
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "1")
    return root


def _wav() -> bytes:
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    header[36:40] = b"data"
    return bytes(header)


async def _mk_user(db: AsyncSession) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_live_golden_path_upload_practice_cross_media_delete(
    db: AsyncSession, blob_patches: Path
) -> None:
    assert immersive_learning_enabled() is True
    a = await _mk_user(db)
    b = await _mk_user(db)

    media_a = await create_media_from_upload(
        db,
        student_id=a,
        filename="a.wav",
        content_type="audio/wav",
        data=_wav(),
        title="media-a",
    )
    await attach_transcript(
        db,
        student_id=a,
        media_id=media_a.id,
        content=(
            "1\n00:00:00,000 --> 00:00:02,000\nhello world\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nshould have known\n"
        ),
        filename="a.srt",
    )
    session = await start_or_resume_session(db, student_id=a, media_id=media_a.id)
    for et, payload in (
        ("play", {}),
        ("pause", {}),
        ("seek", {"to_ms": 100}),
    ):
        await append_telemetry(
            db,
            student_id=a,
            event_type=et,
            media_id=media_a.id,
            session_id=session.id,
            payload=payload,
        )

    from services.immersive.media_service import list_segments
    from services.models import TranscriptSegment

    listed_a = await list_segments(
        db, student_id=a, media_id=media_a.id, offset=0, limit=10
    )
    seg_a_id = uuid.UUID(listed_a["items"][0]["segment_id"])
    seg_a = (
        await db.execute(select(TranscriptSegment).where(TranscriptSegment.id == seg_a_id))
    ).scalar_one()

    listen = await run_listening(
        db,
        student_id=a,
        media_id=media_a.id,
        segment_id=seg_a.id,
        submitted_meaning="hello world",
        session_id=session.id,
    )
    assert "score" in listen

    dic = await run_dictation(
        db,
        student_id=a,
        media_id=media_a.id,
        segment_id=seg_a.id,
        submitted="hello world",
        session_id=session.id,
    )
    assert "score" in dic

    media_b = await create_media_from_upload(
        db,
        student_id=a,
        filename="b.wav",
        content_type="audio/wav",
        data=_wav(),
        title="media-b",
    )
    await attach_transcript(
        db,
        student_id=a,
        media_id=media_b.id,
        content="1\n00:00:00,000 --> 00:00:02,000\nhello world again\n",
        filename="b.srt",
    )
    listed_b = await list_segments(
        db, student_id=a, media_id=media_b.id, offset=0, limit=10
    )
    seg_b_id = uuid.UUID(listed_b["items"][0]["segment_id"])

    xfer = await run_transfer(
        db,
        student_id=a,
        source_media_id=media_a.id,
        source_segment_id=seg_a.id,
        target_media_id=media_b.id,
        target_segment_id=seg_b_id,
        knowledge_ref="lu-vocabulary-hello",
        submitted="hello world",
        expected="hello world",
        distance="near",
    )
    assert xfer["distance"] == "near"

    # IDOR: B cannot read A's media
    with pytest.raises(Exception):
        await get_owned_media(db, student_id=b, media_id=media_a.id)

    deleted = await delete_media_asset(db, a, media_a.id)
    assert deleted["deleted"] is True
    await db.commit()

    left = (
        await db.execute(select(MediaAsset.id).where(MediaAsset.id == media_a.id))
    ).scalar_one_or_none()
    assert left is None

    # Best-effort cleanup; leave orphans rather than fail a passed golden path.
    ids = [str(a), str(b)]
    for table, col in (
        ("media_telemetry_events", "student_id"),
        ("media_sessions", "student_id"),
        ("interaction_events", "student_id"),
        ("learning_events", "student_id"),
        ("mastery_snapshots", "student_id"),
        ("kc_mastery", "student_id"),
        ("memory_claims", "student_id"),
        ("policy_decisions", "student_id"),
    ):
        try:
            await db.execute(
                text(f"DELETE FROM {table} WHERE {col} = ANY(:ids)"),
                {"ids": ids},
            )
        except Exception:
            await db.rollback()
    try:
        await db.execute(
            text("DELETE FROM media_assets WHERE owner_student_id = ANY(:ids)"),
            {"ids": ids},
        )
        await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
        await db.commit()
    except Exception:
        await db.rollback()
        await db.execute(
            text("UPDATE users SET deleted_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        await db.commit()


def test_feature_flag_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "0")
    assert immersive_learning_enabled() is False
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "1")
    assert immersive_learning_enabled() is True

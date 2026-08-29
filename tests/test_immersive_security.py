"""Security-focused Immersive Learning tests (merge hard gate)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.immersive.constants import DEFAULT_MAX_SUBTITLE_BYTES
from services.immersive.media_service import MediaServiceError, get_owned_media
from services.immersive.transcript_parser import TranscriptParseError, parse_srt
from services.models import MediaAsset, User, UserRole
from services.purge_service import delete_media_asset
from services.upload_safety import UploadValidationError, validate_content_type, validate_filename


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


def test_path_traversal_filename_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_filename("../etc/passwd.mp4", allowed_extensions={".mp4"})
    with pytest.raises(UploadValidationError):
        validate_filename("/abs/path.mp4", allowed_extensions={".mp4"})


def test_disallowed_media_extension_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_filename("evil.exe", allowed_extensions={".mp4", ".webm", ".mp3"})


def test_double_extension_disguise_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_filename("payload.php.mp4", allowed_extensions={".mp4"})
    with pytest.raises(UploadValidationError):
        validate_filename("x.exe.webm", allowed_extensions={".webm"})
    # benign multi-dot names with safe inner suffixes still ok
    assert (
        validate_filename("lecture.final.mp4", allowed_extensions={".mp4"})
        == "lecture.final.mp4"
    )


def test_mime_spoof_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_content_type("clip.mp4", "text/html")
    with pytest.raises(UploadValidationError):
        validate_content_type("clip.mp3", "application/javascript")
    # matching / octet-stream allowed
    validate_content_type("clip.mp4", "video/mp4")
    validate_content_type("clip.mp4", "application/octet-stream")


def test_malformed_timestamps_rejected() -> None:
    with pytest.raises(TranscriptParseError):
        parse_srt("1\n99:99:99,000 --> 00:00:01,000\nHi\n")


def test_negative_or_inverted_cues_rejected() -> None:
    with pytest.raises(TranscriptParseError):
        parse_srt("1\n00:00:05,000 --> 00:00:01,000\nBackwards\n")


def test_html_and_script_subtitle_stripped() -> None:
    cues = parse_srt(
        "1\n00:00:00,000 --> 00:00:01,000\n"
        "<b>Hello</b> <script>alert(1)</script> world\n"
    )
    assert cues[0].text == "Hello world"
    assert "script" not in cues[0].text.lower()
    assert "<" not in cues[0].text


def test_oversized_subtitle_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from services.immersive import media_service as ms

    async def _run() -> None:
        # Force owned media lookup to succeed without DB.
        asset = MagicMock()
        asset.id = uuid.uuid4()

        async def fake_owned(*_a, **_k):
            return asset

        monkeypatch.setattr(ms, "get_owned_media", fake_owned)
        huge = "1\n00:00:00,000 --> 00:00:01,000\n" + ("x" * (DEFAULT_MAX_SUBTITLE_BYTES + 10))
        with pytest.raises(MediaServiceError, match="too large"):
            await ms.attach_transcript(
                MagicMock(),
                student_id=uuid.uuid4(),
                media_id=uuid.uuid4(),
                content=huge,
                filename="big.srt",
            )

    asyncio.run(_run())


async def _mk_students(db: AsyncSession, n: int = 2) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for _ in range(n):
        sid = uuid.uuid4()
        db.add(
            User(
                id=sid,
                phone=f"1{str(sid.int)[:10]}",
                role=UserRole.student,
            )
        )
        ids.append(sid)
    await db.flush()
    return ids


@pytest.mark.asyncio
async def test_cross_user_media_idor_returns_404(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.immersive.media_service.upload_media_file",
        lambda *a, **k: None,
    )
    a, b = await _mk_students(db, 2)
    media = MediaAsset(
        id=uuid.uuid4(),
        owner_student_id=a,
        media_type="AUDIO",
        source_type="USER_UPLOAD",
        title="owned-by-a",
        storage_ref=f"immersive/{a}/x.mp3",
        content_provenance="USER_UPLOADED",
        processing_state="READY",
        meta={},
    )
    db.add(media)
    await db.flush()

    with pytest.raises(MediaServiceError) as exc:
        await get_owned_media(db, student_id=b, media_id=media.id)
    assert exc.value.status_code == 404

    await db.execute(text("DELETE FROM media_assets WHERE id = :i"), {"i": str(media.id)})
    await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [str(a), str(b)]})
    await db.commit()


@pytest.mark.asyncio
async def test_media_delete_ownership_and_no_cross_user(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted_refs: list[str] = []

    def fake_delete(ref: str) -> None:
        deleted_refs.append(ref)

    monkeypatch.setattr("services.storage.delete_media_file", fake_delete)
    monkeypatch.setattr(
        "services.immersive.media_service.upload_media_file",
        lambda *a, **k: None,
    )

    a, b = await _mk_students(db, 2)
    media = MediaAsset(
        id=uuid.uuid4(),
        owner_student_id=a,
        media_type="AUDIO",
        source_type="USER_UPLOAD",
        title="to-delete",
        storage_ref=f"immersive/{a}/del.mp3",
        content_provenance="USER_UPLOADED",
        processing_state="READY",
        meta={},
    )
    db.add(media)
    await db.flush()

    with pytest.raises(LookupError):
        await delete_media_asset(db, b, media.id)

    result = await delete_media_asset(db, a, media.id)
    await db.commit()
    assert result["deleted"] is True
    assert deleted_refs == [f"immersive/{a}/del.mp3"]

    left = (
        await db.execute(select(MediaAsset.id).where(MediaAsset.id == media.id))
    ).scalar_one_or_none()
    assert left is None

    await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [str(a), str(b)]})
    await db.commit()


@pytest.mark.asyncio
async def test_unauthorized_delete_without_ownership_fails(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.storage.delete_media_file", lambda *_a, **_k: None)
    missing = uuid.uuid4()
    with pytest.raises(LookupError):
        await delete_media_asset(db, uuid.uuid4(), missing)

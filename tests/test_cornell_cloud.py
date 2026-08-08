"""康奈尔进度云同步：合并落库 + 红线（不写掌握度）+ API 鉴权。"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.cornell_service import (
    delete_progress,
    get_progress,
    put_progress,
)
from services.models import CornellProgress, User, UserRole

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _mk_student(db: AsyncSession) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"1{str(sid.int)[:10]}",
            role=UserRole.student,
        )
    )
    await db.flush()
    return sid


async def _cleanup(db: AsyncSession, sid: uuid.UUID) -> None:
    await db.execute(
        delete(CornellProgress).where(CornellProgress.student_id == sid)
    )
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.mark.asyncio
async def test_put_get_merge_union(db: AsyncSession):
    sid = await _mk_student(db)
    try:
        a = {
            "topicId": "pythagoras",
            "version": 1,
            "mastered": {"q1": True},
            "collapsed": {},
            "selfTest": False,
            "showAnswers": False,
            "updatedAt": "2026-07-28T10:00:00.000Z",
        }
        r1 = await put_progress(db, sid, "pythagoras", a)
        await db.commit()
        assert r1["state"]["mastered"]["q1"] is True

        b = {
            "topicId": "pythagoras",
            "version": 1,
            "mastered": {"q3": True},
            "collapsed": {"m2": True},
            "selfTest": True,
            "showAnswers": False,
            "updatedAt": "2026-07-28T12:00:00.000Z",
        }
        r2 = await put_progress(db, sid, "pythagoras", b)
        await db.commit()
        assert r2["state"]["mastered"] == {"q1": True, "q3": True}
        assert r2["state"]["collapsed"] == {"m2": True}
        assert r2["state"]["selfTest"] is True

        got = await get_progress(db, sid, "pythagoras")
        assert got is not None
        assert got["state"]["mastered"]["q1"] and got["state"]["mastered"]["q3"]

        assert await delete_progress(db, sid, "pythagoras") is True
        await db.commit()
        assert await get_progress(db, sid, "pythagoras") is None
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_topic_mismatch_raises(db: AsyncSession):
    from services.cornell_merge import CornellMergeError

    sid = await _mk_student(db)
    try:
        with pytest.raises(CornellMergeError):
            await put_progress(
                db,
                sid,
                "pythagoras",
                {"topicId": "other", "mastered": {}, "updatedAt": "1"},
            )
    finally:
        await _cleanup(db, sid)


def test_cornell_service_never_imports_mastery_path():
    forbidden = (
        "process_interaction",
        "cognitive_service",
        "mastery_gate",
        "math_grade",
        "kc_mastery",
    )
    for rel in ("services/cornell_service.py", "services/cornell_merge.py"):
        source = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(a.name for a in node.names)
        hits = [f for f in forbidden if any(f in imp for imp in imported)]
        assert not hits, f"{rel} imports mastery path: {hits}"


@pytest.mark.asyncio
async def test_api_put_requires_self(db: AsyncSession):
    """他人 token 写进度 → 403；本人可 PUT/GET。"""
    from obase.auth import create_access_token
    from services.main import app

    sid = await _mk_student(db)
    other = await _mk_student(db)
    await db.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 他人
            tok_other = create_access_token({"sub": str(other)})
            res = await client.put(
                f"/v1/cornell/{sid}/progress/pythagoras",
                json={
                    "state": {
                        "topicId": "pythagoras",
                        "version": 1,
                        "mastered": {"q1": True},
                        "updatedAt": datetime.now(timezone.utc).isoformat(),
                    }
                },
                headers={"Authorization": f"Bearer {tok_other}"},
            )
            assert res.status_code == 403

            # 本人
            tok_self = create_access_token({"sub": str(sid)})
            res = await client.put(
                f"/v1/cornell/{sid}/progress/pythagoras",
                json={
                    "state": {
                        "topicId": "pythagoras",
                        "version": 1,
                        "mastered": {"q1": True},
                        "collapsed": {},
                        "selfTest": False,
                        "showAnswers": False,
                        "updatedAt": "2026-07-28T10:00:00.000Z",
                    }
                },
                headers={"Authorization": f"Bearer {tok_self}"},
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["state"]["mastered"]["q1"] is True

            res = await client.get(
                f"/v1/cornell/{sid}/progress/pythagoras",
                headers={"Authorization": f"Bearer {tok_self}"},
            )
            assert res.status_code == 200
            assert res.json()["topic_id"] == "pythagoras"
    finally:
        await _cleanup(db, sid)
        await _cleanup(db, other)


@pytest.mark.asyncio
async def test_purge_list_includes_cornell():
    from services.purge_service import _STUDENT_TABLES

    assert ("cornell_progress", "student_id") in _STUDENT_TABLES

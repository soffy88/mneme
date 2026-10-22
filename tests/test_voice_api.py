"""朗读 /v1/tts、陪学设置/日志、语音 WS 鉴权与授权、purge 清单、工具面（无联网/摄像头工具）。

真实 HTTP + 测试库（同 tests/test_prereq_writeback_grants.py 写法）；speech 容器以 fake 替换。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services import companion_service as svc
from services.main import app
from services.models import ParentStudent, User, UserRole
from services.routers import voice as voice_router
from services.speech_client import SpeechClient
from services.tool_grants import DEFAULT_STUDENT_TOOLS, VOICE_TOOLS

from .db_test_helpers import cleanup_test_student


def _tok(uid):
    return create_access_token({"sub": str(uid)})


def _h(uid):
    return {"Authorization": f"Bearer {_tok(uid)}"}


@pytest.fixture
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def actors(db, monkeypatch):
    admin, stu, par, other = (uuid.uuid4() for _ in range(4))
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin))
    db.add_all([
        User(id=admin, role=UserRole.parent, name="管理员"),
        User(id=stu, role=UserRole.student, name="语音学生"),
        User(id=par, role=UserRole.parent, name="家长"),
        User(id=other, role=UserRole.parent, name="别人家长"),
    ])
    await db.commit()
    db.add(ParentStudent(parent_id=par, student_id=stu))
    await db.commit()
    yield {"admin": admin, "stu": stu, "par": par, "other": other}
    await db.rollback()
    for t in ("companion_messages", "companion_usage", "companion_settings"):
        await db.execute(text(f"DELETE FROM {t} WHERE student_id = :s"), {"s": str(stu)})
    await db.execute(text("DELETE FROM agent.user_grants WHERE student_id = ANY(:s)"), {"s": [par, stu]})
    await db.execute(text("DELETE FROM parent_student WHERE parent_id = :p"), {"p": par})
    await db.commit()
    for uid in (stu, par, other, admin):
        await cleanup_test_student(db, uid)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class _MemStore:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v):
        self.d[k] = v


async def test_tts_endpoint(client, actors, monkeypatch):
    sc = SpeechClient(store=_MemStore())
    seen = []

    async def synth_raw(spoken, speed=1.0):
        seen.append(spoken)
        return b"RIFF....WAVE"

    monkeypatch.setattr(sc, "synth_raw", synth_raw)
    monkeypatch.setattr(voice_router, "_speech", lambda: sc)

    async def ok(*a, **k):
        return True

    monkeypatch.setattr(voice_router, "_rate_ok", ok)
    r = await client.post("/v1/tts", json={"text": "$(a+b)^2$"})
    assert r.status_code == 401
    r = await client.post("/v1/tts", json={"text": "$(a+b)^2$"}, headers=_h(actors["stu"]))
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.headers["x-tts-cache"] == "miss" and seen == ["诶加必的平方"]
    r2 = await client.post("/v1/tts", json={"text": "$(a+b)^2$"}, headers=_h(actors["stu"]))
    assert r2.headers["x-tts-cache"] == "hit" and len(seen) == 1


async def test_settings_permissions(client, actors):
    sid = actors["stu"]
    r = await client.get(f"/v1/companion/{sid}/settings", headers=_h(sid))
    assert r.status_code == 200 and r.json()["name"] == "小智" and r.json()["daily_cap_minutes"] == 30
    assert (await client.put(f"/v1/companion/{sid}/settings", json={"daily_cap_minutes": 200},
                             headers=_h(sid))).status_code == 403
    assert (await client.put(f"/v1/companion/{sid}/settings", json={"name": "小星"},
                             headers=_h(actors["other"]))).status_code == 403
    assert (await client.put(f"/v1/companion/{sid}/settings", json={"name": "老婆"},
                             headers=_h(actors["par"]))).status_code == 422
    r = await client.put(f"/v1/companion/{sid}/settings",
                         json={"name": "小星", "daily_cap_minutes": 15, "session_limit_minutes": 10},
                         headers=_h(actors["par"]))
    assert r.status_code == 200 and r.json()["name"] == "小星"
    r = await client.get(f"/v1/companion/{sid}/settings", headers=_h(actors["par"]))
    assert r.json()["daily_cap_minutes"] == 15 and r.json()["session_limit_minutes"] == 10
    assert (await client.get(f"/v1/companion/{sid}/settings", headers=_h(actors["other"]))).status_code == 403


async def test_logs_visible_to_parent_and_usage(client, actors, db):
    sid = str(actors["stu"])
    await svc.log_message(db, student_id=sid, session_id=str(uuid.uuid4()), mode="companion", role="student",
                          content="做我女朋友", flags=["romance"])
    await svc.add_usage(db, sid, 120)
    await svc.add_usage(db, sid, 30)
    assert await svc.used_seconds_today(db, sid) == 150
    r = await client.get(f"/v1/companion/{sid}/logs", headers=_h(actors["par"]))
    assert r.status_code == 200 and r.json()["items"][0]["flags"] == ["romance"]
    assert (await client.get(f"/v1/companion/{sid}/logs", headers=_h(actors["other"]))).status_code == 403


async def test_ws_auth_and_grants(actors, db):
    from obase.user_grants import set_grant

    assert VOICE_TOOLS <= DEFAULT_STUDENT_TOOLS
    u, err = await voice_router.authenticate_ws("garbage", "tutor")
    assert u is None and err == "unauthorized"
    for mode in ("tutor", "companion"):
        u, err = await voice_router.authenticate_ws(_tok(actors["stu"]), mode)
        assert err == "" and u.id == actors["stu"]
    u, err = await voice_router.authenticate_ws(_tok(actors["par"]), "companion")
    assert err == "forbidden"
    admin = await db.get(User, actors["admin"])
    await set_grant(db, admin_user=admin, student_id=actors["par"], enabled_tools=["VoiceTutor"])
    await db.commit()
    u, err = await voice_router.authenticate_ws(_tok(actors["par"]), "tutor")
    assert err == ""
    u, err = await voice_router.authenticate_ws(_tok(actors["par"]), "companion")
    assert err == "forbidden"


def test_purge_inventory_has_companion_tables():
    from services.purge_service import _STUDENT_TABLES

    names = {t for t, _ in _STUDENT_TABLES}
    assert {"companion_settings", "companion_usage", "companion_messages"} <= names


def test_tutor_tools_have_no_web_camera_browse():
    from mneme_agent.assembly.tutor_loop import build_tools

    names = " ".join(getattr(t, "name", str(t)) for t in build_tools("http://x", student_id="s", kc_ids=[]))
    low = names.lower()
    for bad in ("web", "browse", "camera", "screen", "internet", "fetch_url"):
        assert bad not in low, bad

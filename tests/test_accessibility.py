"""U.23 UDL 无障碍测试：偏好读写 + 公式朗读 + 低带宽裁剪。"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.accessibility_service import flatten_rich_content
from services.main import app
from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    Textbook,
    User,
    UserRole,
)


@pytest.fixture(autouse=True)
def register_provider_mocks():
    """ProviderRegistry 是进程级单例，_instance 在首次调用前是 None——main.py 里各处
    `if ProviderRegistry._instance else None` 的判断、以及其它测试文件都依赖这一点
    （它们没显式注册的 provider 类目会走"_instance 为 None → 跳过"的分支，而不是真
    去查未注册的 provider 报 ProviderNotFoundError）。本文件注册了 provider 后必须在
    teardown 用 ProviderRegistry.clear() 复位，否则会让"_instance 是否为 None"这个
    全局单例状态泄漏给后面按字母序跑的测试文件（已实测坑过 test_essay_guide.py 和
    test_oprim_llm.py）。"""
    from obase.provider_registry import ProviderRegistry

    class MockTTSCaller:
        async def __call__(self, *, text: str, language: str = "zh", **kwargs):
            return "bW9ja19hdWRpb19kYXRh"

    ProviderRegistry.clear()
    ProviderRegistry.register("tts", "default", MockTTSCaller(), replace=True)
    yield
    ProviderRegistry.clear()


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
            phone=f"177{str(sid)[:8]}",
            role=UserRole.student,
            name="U",
            grade="高一",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def seed_ku(db: AsyncSession):
    tb_id = f"tb-a11y-{uuid.uuid4().hex[:8]}"
    c_id = f"cl-a11y-{uuid.uuid4().hex[:8]}"
    ku_id = f"ku-a11y-{uuid.uuid4().hex[:8]}"
    db.add(
        Textbook(
            id=tb_id,
            subject="math",
            grade="高一",
            edition="测试版",
            book_name="无障碍测试教材",
        )
    )
    await db.flush()
    db.add(
        KnowledgeCluster(id=c_id, textbook_id=tb_id, name="测试章节", display_order=1)
    )
    await db.flush()
    db.add(
        KnowledgeUnit(
            id=ku_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="测试知识点",
            description="一个用于测试的知识点描述",
            rich_content={
                "definition": "这是定义文本。",
                "example": "这是示例文本。",
                "confusable": [{"idiom": "干扰项", "diff": "区别说明"}],
                "empty_field": None,
            },
        )
    )
    await db.commit()
    yield {"tb_id": tb_id, "c_id": c_id, "ku_id": ku_id}
    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id))
    await db.execute(
        delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
    )
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 偏好读写 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_accessibility_defaults(student):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/users/{sid}/accessibility", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["font_size"] == "normal"
    assert body["low_bandwidth"] is False


@pytest.mark.asyncio
async def test_set_accessibility_partial_update_persists(student, db):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            f"/v1/users/{sid}/accessibility",
            json={"font_size": "large", "low_bandwidth": True},
            headers=_h(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["font_size"] == "large"
    assert body["low_bandwidth"] is True
    assert body["line_height"] == "normal"  # 未传的字段保留默认

    # 另开查询验证真落库（不是同一 ORM 对象内存里看得见）
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r2 = await c.get(f"/v1/users/{sid}/accessibility", headers=_h(token))
    assert r2.json()["font_size"] == "large"


@pytest.mark.asyncio
async def test_set_accessibility_unknown_field_rejected_at_service_layer(student, db):
    """API 层的 AccessibilityPrefsReq 只声明了 4 个字段，未知字段会被 Pydantic 静默丢弃，
    永远到不了 service 层的校验——这里直接测 service 函数，才能测到这条校验。"""
    from services.accessibility_service import set_accessibility_prefs

    sid, _ = student
    result = await set_accessibility_prefs(
        db, sid, {"font_size": "large", "bogus": "x"}
    )
    assert "error" in result
    assert "bogus" in result["error"]


@pytest.mark.asyncio
async def test_cannot_set_other_students_accessibility(student):
    sid, token = student
    other = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            f"/v1/users/{other}/accessibility",
            json={"font_size": "large"},
            headers=_h(token),
        )
    assert r.status_code == 403


# ── 公式朗读 ─────────────────────────────────────────────────────────────────


def test_flatten_rich_content_skips_none_and_flattens_nested():
    text = flatten_rich_content(
        {
            "a": "文本A",
            "b": None,
            "c": ["文本B", "文本C"],
            "d": {"nested": "文本D"},
        }
    )
    assert "文本A" in text
    assert "文本B" in text
    assert "文本C" in text
    assert "文本D" in text
    assert "None" not in text


def test_flatten_rich_content_empty():
    assert flatten_rich_content(None) == ""
    assert flatten_rich_content({}) == ""


@pytest.mark.asyncio
async def test_read_aloud_ku_returns_audio(student, seed_ku):
    _, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            f"/v1/knowledge-points/{seed_ku['ku_id']}/read-aloud",
            headers=_h(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert "定义文本" in body["text"]
    assert body["audio_b64"]


@pytest.mark.asyncio
async def test_read_aloud_ku_not_found(student):
    _, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/knowledge-points/does-not-exist/read-aloud",
            headers=_h(token),
        )
    assert r.status_code == 404


# ── 低带宽模式裁剪 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_point_low_bandwidth_omits_rich_content(student, seed_ku):
    _, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        normal = await c.get(
            f"/v1/knowledge-points/{seed_ku['ku_id']}", headers=_h(token)
        )
        lb = await c.get(
            f"/v1/knowledge-points/{seed_ku['ku_id']}",
            params={"low_bandwidth": "true"},
            headers=_h(token),
        )
    assert normal.json()["rich_content"] is not None
    assert lb.json()["rich_content"] is None


@pytest.mark.asyncio
async def test_solve_low_bandwidth_skips_svg():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        normal = await c.post(
            "/v1/solve", params={"kc_id": "GDMATH-FUNC-01", "expression": "x**2-4"}
        )
        lb = await c.post(
            "/v1/solve",
            params={
                "kc_id": "GDMATH-FUNC-01",
                "expression": "x**2-4",
                "low_bandwidth": "true",
            },
        )
    assert normal.status_code == 200
    assert lb.status_code == 200
    assert normal.json()["svg"]  # 正常模式有 svg
    assert lb.json()["svg"] == ""  # 低带宽模式跳过生成

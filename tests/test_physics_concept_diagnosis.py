"""U.19 物理概念优先范式（FCI式诊断→认知冲突→计算迁移）测试。

覆盖：oprim 诊断题生成 / oskill 组合 / omodul 事务 / 服务层会话 / API 端点。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    SocraticMode,
    SocraticSession,
    Textbook,
    User,
    UserRole,
)


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
            name="P",
            grade="高一",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(SocraticSession).where(SocraticSession.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def physics_kus(db: AsyncSession):
    """一个命中误解库的物理 KU（牛顿第一定律）+ 一个不命中的（etc 收费通道模型）。"""
    tb_id = f"test-phys-tb-{uuid.uuid4().hex[:8]}"
    c_id = f"test-phys-c-{uuid.uuid4().hex[:8]}"
    ku_hit_id = f"test-phys-ku-hit-{uuid.uuid4().hex[:8]}"
    ku_miss_id = f"test-phys-ku-miss-{uuid.uuid4().hex[:8]}"

    db.add(
        Textbook(
            id=tb_id,
            subject="physics",
            grade="高一",
            edition="测试版",
            book_name="测试物理必修",
        )
    )
    await db.flush()
    db.add(KnowledgeCluster(id=c_id, textbook_id=tb_id, name="第一章", display_order=1))
    await db.flush()
    db.add(
        KnowledgeUnit(
            id=ku_hit_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="牛顿第一定律与惯性",
            description="测试",
            prerequisites=[],
            related_kus=[],
            difficulty=0.5,
            exam_frequency="high",
            question_types=["计算题"],
            ku_type="concept",
        )
    )
    db.add(
        KnowledgeUnit(
            id=ku_miss_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="ETC与人工收费通道模型",
            description="测试",
            prerequisites=[],
            related_kus=[],
            difficulty=0.5,
            exam_frequency="mid",
            question_types=["计算题"],
            ku_type="model",
        )
    )
    await db.commit()

    yield ku_hit_id, ku_miss_id

    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id))
    await db.execute(
        delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
    )
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── oprim 层 ───────────────────────────────────────────────────────────────


class _GoodDiagnosticLLM:
    async def __call__(self, **kwargs):
        return {
            "content": (
                '{"scenario":"一个物体在光滑水平面上以恒定速度运动，不受任何水平方向的力。",'
                '"option_a":"物体会因为没有力推它而逐渐减速直至停止",'
                '"option_b":"物体会保持恒定速度一直运动下去",'
                '"misconception_option":"A"}'
            ),
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


@pytest.mark.asyncio
async def test_generate_concept_diagnostic_returns_two_options():
    from oprim._physics_concept_diagnostic import generate_concept_diagnostic

    result = await generate_concept_diagnostic(
        misconception_label="有力才有速度",
        remediation="惯性演示",
        ku_name="牛顿第一定律",
        caller=_GoodDiagnosticLLM(),
    )
    assert result.option_a and result.option_b
    assert result.misconception_option in ("A", "B")


@pytest.mark.asyncio
async def test_generate_concept_diagnostic_malformed_json_falls_back():
    """LLM 返回非法 JSON 时用误解 label/remediation 兜底，不崩溃。"""
    from oprim._physics_concept_diagnostic import generate_concept_diagnostic

    class BadLLM:
        async def __call__(self, **kwargs):
            return {"content": "不是JSON", "usage": {}}

    result = await generate_concept_diagnostic(
        misconception_label="误解陈述",
        remediation="重建方向",
        ku_name="测试KU",
        caller=BadLLM(),
    )
    assert result.option_a == "误解陈述"
    assert result.option_b == "重建方向"
    assert result.misconception_option == "A"


# ── oskill 层 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_physics_concept_diagnosis_finds_candidate():
    from oskill._physics_concept_diagnosis import physics_concept_diagnosis

    result = await physics_concept_diagnosis(
        ku_name="牛顿第一定律与惯性", ku_id="x", caller=_GoodDiagnosticLLM()
    )
    assert result is not None
    assert result.misconception_id == "PHYS-FORCE-MOTION"
    assert result.misconception_option in ("A", "B")


@pytest.mark.asyncio
async def test_physics_concept_diagnosis_no_candidate_returns_none():
    from oskill._physics_concept_diagnosis import physics_concept_diagnosis

    result = await physics_concept_diagnosis(
        ku_name="ETC与人工收费通道模型", ku_id="x", caller=_GoodDiagnosticLLM()
    )
    assert result is None


# ── omodul 层 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_has_candidate_branch():
    import tempfile

    from omodul import (
        PhysicsConceptDiagnosisConfig,
        PhysicsConceptDiagnosisInput,
        physics_concept_diagnosis_workflow,
    )

    result = await physics_concept_diagnosis_workflow(
        config=PhysicsConceptDiagnosisConfig(),
        input_data=PhysicsConceptDiagnosisInput(
            ku_name="牛顿第一定律与惯性", ku_id="x", user_id="anon"
        ),
        output_dir=tempfile.mkdtemp(),
        caller=_GoodDiagnosticLLM(),
    )
    assert result["status"] == "ok"
    assert result["has_candidate"] is True
    assert result["misconception_option"] in ("A", "B")
    assert result["remediation"]


@pytest.mark.asyncio
async def test_workflow_no_candidate_branch():
    import tempfile

    from omodul import (
        PhysicsConceptDiagnosisConfig,
        PhysicsConceptDiagnosisInput,
        physics_concept_diagnosis_workflow,
    )

    result = await physics_concept_diagnosis_workflow(
        config=PhysicsConceptDiagnosisConfig(),
        input_data=PhysicsConceptDiagnosisInput(
            ku_name="ETC与人工收费通道模型", ku_id="x", user_id="anon"
        ),
        output_dir=tempfile.mkdtemp(),
        caller=_GoodDiagnosticLLM(),
    )
    assert result["status"] == "ok"
    assert result["has_candidate"] is False


# ── 服务层 + API ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_concept_diagnosis_rejects_non_physics_ku(db, student):
    """非物理 KU 不诊断（U.19 本轮只做物理，英语/数学等走原有路径）。"""
    from services.physics_service import start_concept_diagnosis

    sid, _ = student
    tb_id = f"test-math-tb-{uuid.uuid4().hex[:8]}"
    c_id = f"test-math-c-{uuid.uuid4().hex[:8]}"
    ku_id = f"test-math-ku-{uuid.uuid4().hex[:8]}"
    db.add(Textbook(id=tb_id, subject="math", grade="高一", edition="v", book_name="b"))
    await db.flush()
    db.add(KnowledgeCluster(id=c_id, textbook_id=tb_id, name="c", display_order=1))
    await db.flush()
    db.add(
        KnowledgeUnit(
            id=ku_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="牛顿迭代法",
            prerequisites=[],
            related_kus=[],
            difficulty=0.5,
            exam_frequency="mid",
            question_types=[],
            ku_type="method",
        )
    )
    await db.commit()

    result = await start_concept_diagnosis(db, ku_id, sid)
    assert result["has_candidate"] is False
    assert "error" in result

    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == ku_id))
    await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.id == c_id))
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


@pytest.mark.asyncio
async def test_start_concept_diagnosis_unknown_ku(db, student):
    from services.physics_service import start_concept_diagnosis

    sid, _ = student
    result = await start_concept_diagnosis(db, "does-not-exist", sid)
    assert result["has_candidate"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_concept_diagnosis_start_api_never_leaks_misconception_option(
    db, student, physics_kus
):
    """API 响应不能下发 misconception_option（否则诊断失去意义）。

    未注册 ProviderRegistry 时 omodul 走内置 _MockCaller 兜底（同
    test_guide_services.py 对 force_analysis/reading_guide 的既有测试方式），
    不需要额外 mock。
    """
    ku_hit, _ = physics_kus
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/physics/concept-diagnosis/start",
            params={"ku_id": ku_hit},
            headers=_h(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["has_candidate"] is True
    assert "misconception_option" not in body
    assert "misconception_id" not in body
    session_id = body["session_id"]

    # 会话确实落库且记住了 misconception_option（服务端知情，客户端不知情）
    from sqlalchemy import select

    row = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == uuid.UUID(session_id))
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.mode == SocraticMode.concept_diagnosis
    assert row.messages["misconception_option"] == "A"


@pytest.mark.asyncio
async def test_submit_holds_misconception_returns_remediation(db, student):
    from services.physics_service import submit_concept_diagnosis_answer

    sid, _ = student
    session_id = uuid.uuid4()
    db.add(
        SocraticSession(
            id=session_id,
            student_id=sid,
            mode=SocraticMode.concept_diagnosis,
            messages={
                "ku_id": "test-ku",
                "misconception_id": "PHYS-FORCE-MOTION",
                "remediation": "惯性演示 + 匀速无合力冲突案例",
                "misconception_option": "A",
                "answered": False,
            },
        )
    )
    await db.commit()

    result = await submit_concept_diagnosis_answer(db, session_id, "A")
    assert result["holds_misconception"] is True
    assert result["remediation"] == "惯性演示 + 匀速无合力冲突案例"


@pytest.mark.asyncio
async def test_submit_correct_choice_no_remediation(db, student):
    from services.physics_service import submit_concept_diagnosis_answer

    sid, _ = student
    session_id = uuid.uuid4()
    db.add(
        SocraticSession(
            id=session_id,
            student_id=sid,
            mode=SocraticMode.concept_diagnosis,
            messages={
                "ku_id": "test-ku",
                "misconception_id": "PHYS-FORCE-MOTION",
                "remediation": "惯性演示 + 匀速无合力冲突案例",
                "misconception_option": "A",
                "answered": False,
            },
        )
    )
    await db.commit()

    result = await submit_concept_diagnosis_answer(db, session_id, "B")
    assert result["holds_misconception"] is False
    assert result["remediation"] is None


@pytest.mark.asyncio
async def test_submit_does_not_update_mastery(db, student):
    """诊断题不影响 BKT/FSRS：无 KCMastery 行产生。"""
    from services.physics_service import submit_concept_diagnosis_answer
    from services.models import KCMastery

    sid, _ = student
    session_id = uuid.uuid4()
    ku_id = f"test-ku-{uuid.uuid4().hex[:8]}"
    db.add(
        SocraticSession(
            id=session_id,
            student_id=sid,
            mode=SocraticMode.concept_diagnosis,
            messages={
                "ku_id": ku_id,
                "misconception_id": "PHYS-FORCE-MOTION",
                "remediation": "惯性演示",
                "misconception_option": "A",
                "answered": False,
            },
        )
    )
    await db.commit()

    await submit_concept_diagnosis_answer(db, session_id, "A")

    from sqlalchemy import select

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == ku_id
            )
        )
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_concept_diagnosis_submit_api(db, student):
    sid, token = student
    session_id = uuid.uuid4()
    db.add(
        SocraticSession(
            id=session_id,
            student_id=sid,
            mode=SocraticMode.concept_diagnosis,
            messages={
                "ku_id": "test-ku",
                "misconception_id": "PHYS-FORCE-MOTION",
                "remediation": "惯性演示",
                "misconception_option": "A",
                "answered": False,
            },
        )
    )
    await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            f"/v1/physics/concept-diagnosis/{session_id}/submit",
            params={"chosen_option": "A"},
            headers=_h(token),
        )
    assert r.status_code == 200
    assert r.json()["holds_misconception"] is True


@pytest.mark.asyncio
async def test_concept_diagnosis_submit_requires_session_owner(db, student):
    """会话归属他人：403（复用既有 _ensure_session_owner 鉴权）。"""
    other_sid = uuid.uuid4()
    db.add(
        User(
            id=other_sid,
            phone=f"188{str(other_sid)[:8]}",
            role=UserRole.student,
            name="O",
            grade="高一",
        )
    )
    await db.commit()

    sid, token = student
    session_id = uuid.uuid4()
    db.add(
        SocraticSession(
            id=session_id,
            student_id=other_sid,
            mode=SocraticMode.concept_diagnosis,
            messages={
                "ku_id": "test-ku",
                "misconception_id": "PHYS-FORCE-MOTION",
                "remediation": "惯性演示",
                "misconception_option": "A",
            },
        )
    )
    await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            f"/v1/physics/concept-diagnosis/{session_id}/submit",
            params={"chosen_option": "A"},
            headers=_h(token),
        )
    assert r.status_code == 403

    await db.execute(delete(SocraticSession).where(SocraticSession.id == session_id))
    await db.execute(delete(User).where(User.id == other_sid))
    await db.commit()


@pytest.mark.asyncio
async def test_concept_diagnosis_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/v1/physics/concept-diagnosis/start", params={"ku_id": "x"})
    assert r.status_code == 401

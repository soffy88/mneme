"""
引导服务测试 — Epic M.4 受力分析引导 + M.5 阅读理解引导

强制红线测试：
  test_force_analysis_never_gives_answer
  test_reading_guide_never_gives_answer
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
from services.models import SocraticSession, SocraticMode, User, UserRole

# ── fixtures ─────────────────────────────────────────────────────────────────


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
            phone=f"155{str(sid)[:8]}",
            role=UserRole.student,
            name="G",
            grade="高二",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(SocraticSession).where(SocraticSession.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── force analysis 红线测试（核心）────────────────────────────────────────────

_ANSWER_PATTERNS = [
    # 受力图完整描述
    "受重力 mg 向下，支持力 N 向上",
    "受到重力和支持力，合力为零",
    # 完整方程
    "N - mg = 0",
    "F_N = mg",
    "合外力等于零，即 ΣF = 0",
    # 直接给结论
    "所以受力平衡，加速度为零",
    "直接可以列方程",
]

_GUIDE_QUESTION_MARKERS = [
    "？",
    "吗",
    "呢",
    "如何",
    "什么",
    "哪",
    "你觉得",
    "分析",
    "请",
    "怎么",
    "?",
    "what",
    "how",
    "which",
    "can you",
    "do you",
    "where",
]


@pytest.mark.asyncio
async def test_force_analysis_never_gives_answer():
    """红线测试：受力分析引导绝不直接给出受力图描述或完整方程。"""
    from oskill._physics_force_analysis_guide import physics_force_analysis_guide

    # 模拟一个"恶意"LLM，试图直接给出答案
    class LeakyLLM:
        async def __call__(self, **kwargs):
            # 返回一个含有答案的响应
            return {
                "content": '{"assistant_text":"这个物体受重力mg向下，支持力N向上，合力为零，N-mg=0","equation_ready":true,"answer_leaked":false}',
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

    result = await physics_force_analysis_guide(
        question_text="一个物体静止在水平面上，分析受力情况。",
        student_messages=["我不知道怎么分析"],
        caller=LeakyLLM(),
    )

    # 红线保护应已触发
    assert result.answer_leaked is True
    # 回复必须是引导式，不能含完整方程
    response = result.assistant_text
    for pattern in ["N - mg", "合力为零", "mg向下，支持力N向上"]:
        assert pattern not in response, (
            f"红线违规：回复包含答案片段 '{pattern}': {response!r}"
        )
    # 回复必须是问句或引导语
    has_guide_marker = any(m in response for m in _GUIDE_QUESTION_MARKERS)
    assert has_guide_marker, f"回复不是引导式提问: {response!r}"


@pytest.mark.asyncio
async def test_force_analysis_opening_is_question():
    """开场必须是引导问，不含答案。"""
    from oskill._physics_force_analysis_guide import physics_force_analysis_guide

    result = await physics_force_analysis_guide(
        question_text="斜面上有一个物体，求摩擦力大小。",
        student_messages=None,
        caller=None,  # 开场不调用 LLM
    )
    assert result.equation_ready is False
    assert result.answer_leaked is False
    has_guide = any(m in result.assistant_text for m in _GUIDE_QUESTION_MARKERS)
    assert has_guide, f"开场不是引导问: {result.assistant_text!r}"


@pytest.mark.asyncio
async def test_force_analysis_clean_response_passes():
    """正常引导式回复不触发红线。"""
    from oskill._physics_force_analysis_guide import physics_force_analysis_guide

    class GoodLLM:
        async def __call__(self, **kwargs):
            return {
                "content": '{"assistant_text":"你觉得这个物体处于什么运动状态？","equation_ready":false,"answer_leaked":false}',
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

    result = await physics_force_analysis_guide(
        question_text="一个滑块在斜面上匀速下滑，分析受力。",
        student_messages=["好像是匀速运动？"],
        caller=GoodLLM(),
    )
    assert result.answer_leaked is False
    assert "你觉得" in result.assistant_text or "运动状态" in result.assistant_text


# ── reading guide 红线测试（核心）─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reading_guide_never_gives_answer():
    """红线测试：阅读引导绝不直接给出题目答案。"""
    from oskill._reading_comprehension_guide import reading_comprehension_guide

    class LeakyReadingLLM:
        async def __call__(self, **kwargs):
            # 试图直接给出答案
            return {
                "content": '{"assistant_text":"这道题的答案是：作者表达了对故乡的深切思念，具体体现在第二段第三句话中。","located_passage":true,"answer_leaked":false}',
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

    result = await reading_comprehension_guide(
        article_text="故乡的山水总是令我难以忘怀。（省略正文）",
        question="作者在文中表达了怎样的情感？",
        subject="chinese",
        student_messages=["我不知道答案"],
        caller=LeakyReadingLLM(),
    )

    # 回复不应包含"答案是"
    assert "答案是" not in result.assistant_text, (
        f"红线违规：直接给出答案: {result.assistant_text!r}"
    )


@pytest.mark.asyncio
async def test_reading_guide_chinese_opening_is_question():
    """语文阅读开场必须是引导问，不含答案。"""
    from oskill._reading_comprehension_guide import reading_comprehension_guide

    result = await reading_comprehension_guide(
        article_text="春天来了，花儿开放。",
        question="作者表达了什么情感？",
        subject="chinese",
        student_messages=None,
        caller=None,
    )
    assert result.answer_leaked is False
    has_guide = any(m in result.assistant_text for m in _GUIDE_QUESTION_MARKERS)
    assert has_guide, f"开场不是引导问: {result.assistant_text!r}"


@pytest.mark.asyncio
async def test_reading_guide_english_opening_is_question():
    """英语阅读开场必须是英文引导问。"""
    from oskill._reading_comprehension_guide import reading_comprehension_guide

    result = await reading_comprehension_guide(
        article_text="The sun rises in the east and sets in the west.",
        question="What does the author mean by this passage?",
        subject="english",
        student_messages=None,
        caller=None,
    )
    assert result.answer_leaked is False
    # 应该是英文
    assert any(c.isalpha() and ord(c) < 128 for c in result.assistant_text), (
        "英文引导应包含英文字符"
    )
    has_guide = any(
        m in result.assistant_text.lower()
        for m in ["?", "what", "where", "can you", "do you"]
    )
    assert has_guide, f"英文开场不是引导问: {result.assistant_text!r}"


@pytest.mark.asyncio
async def test_reading_guide_subject_distinction():
    """subject 参数正确区分 english/chinese 引导语境。"""
    from oskill._reading_comprehension_guide import reading_comprehension_guide

    result_zh = await reading_comprehension_guide(
        article_text="天空中飘着白云。",
        question="文章表达了什么？",
        subject="chinese",
        student_messages=None,
        caller=None,
    )
    result_en = await reading_comprehension_guide(
        article_text="Clouds float in the sky.",
        question="What does this passage express?",
        subject="english",
        student_messages=None,
        caller=None,
    )
    # 中文版应包含中文
    assert any(ord(c) > 127 for c in result_zh.assistant_text)
    # 英文版应包含英文字母
    assert any(c.isalpha() and ord(c) < 128 for c in result_en.assistant_text)


# ── API 端点测试 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_analysis_start_api(db, student):
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/physics/force-analysis/start",
            params={"question_text": "一个物体静止在斜面上，分析受力。"},
            headers=_headers(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "first_question" in body
    assert body["first_question"]  # 非空
    # 验证 session 已入库
    from sqlalchemy import select

    sess = (
        await db.execute(
            select(SocraticSession).where(
                SocraticSession.id == uuid.UUID(body["session_id"])
            )
        )
    ).scalar_one_or_none()
    assert sess is not None
    assert sess.mode == SocraticMode.force_analysis


@pytest.mark.asyncio
async def test_force_analysis_message_api(db, student):
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        start_r = await c.post(
            "/v1/physics/force-analysis/start",
            params={"question_text": "一个小球在水中匀速下沉，分析受力。"},
            headers=_headers(token),
        )
    session_id = start_r.json()["session_id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        msg_r = await c.post(
            "/v1/physics/force-analysis/message",
            params={"session_id": session_id, "message": "受重力和浮力？"},
            headers=_headers(token),
        )
    assert msg_r.status_code == 200
    content = msg_r.text
    assert "data:" in content
    assert "reply" in content


@pytest.mark.asyncio
async def test_reading_guide_start_api(db, student):
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/reading/guide/start",
            json={
                "article_text": "鲁迅在文章中描述了故乡的变迁。",
                "question": "文章表达了作者怎样的情感？",
                "subject": "chinese",
            },
            headers=_headers(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "first_question" in body
    assert body["subject"] == "chinese"


@pytest.mark.asyncio
async def test_reading_guide_english_subject(db, student):
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/reading/guide/start",
            json={
                "article_text": "The quick brown fox jumps over the lazy dog.",
                "question": "What does the author describe?",
                "subject": "english",
            },
            headers=_headers(token),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "english"
    assert body["first_question"]


@pytest.mark.asyncio
async def test_reading_guide_message_api(db, student):
    sid, token = student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        start_r = await c.post(
            "/v1/reading/guide/start",
            json={
                "article_text": "春天来了，万物复苏。",
                "question": "作者想表达什么？",
                "subject": "chinese",
            },
            headers=_headers(token),
        )
    session_id = start_r.json()["session_id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        msg_r = await c.post(
            "/v1/reading/guide/message",
            params={"session_id": session_id, "message": "表达了对春天的喜爱？"},
            headers=_headers(token),
        )
    assert msg_r.status_code == 200
    assert "reply" in msg_r.text


@pytest.mark.asyncio
async def test_force_analysis_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/physics/force-analysis/start",
            params={"question_text": "测试"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_reading_guide_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/reading/guide/start",
            json={"article_text": "test", "question": "test", "subject": "english"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_force_analysis_session_not_found(db, student):
    """会话不存在：鉴权加固后先做归属校验，直接 404（原为 SSE 内嵌 error）。"""
    sid, token = student
    fake_sid = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/physics/force-analysis/message",
            params={"session_id": fake_sid, "message": "hello"},
            headers=_headers(token),
        )
    assert r.status_code == 404


# ── omodul 层测试 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_analysis_workflow_returns_dict():
    """omodul.force_analysis_workflow 返回结构化 dict。"""
    from omodul import force_analysis_workflow, ForceAnalysisConfig, ForceAnalysisInput
    import tempfile

    result = await force_analysis_workflow(
        config=ForceAnalysisConfig(),
        input_data=ForceAnalysisInput(
            question_text="一物体在斜面上静止，分析受力。",
            student_messages=[],
            user_id="test-user",
        ),
        output_dir=tempfile.mkdtemp(),
    )
    assert result["status"] == "ok"
    assert "assistant_text" in result
    assert "equation_ready" in result
    assert isinstance(result["equation_ready"], bool)


@pytest.mark.asyncio
async def test_reading_guide_workflow_subject_in_response():
    """omodul.reading_guide_workflow 在返回中带 subject 字段。"""
    from omodul import reading_guide_workflow, ReadingGuideConfig, ReadingGuideInput
    import tempfile

    for subj in ["chinese", "english"]:
        result = await reading_guide_workflow(
            config=ReadingGuideConfig(),
            input_data=ReadingGuideInput(
                article_text="Test article.",
                question="What is the theme?",
                subject=subj,
                student_messages=[],
                user_id="test",
            ),
            output_dir=tempfile.mkdtemp(),
        )
        assert result["status"] == "ok"
        assert result.get("subject") == subj
        assert "assistant_text" in result

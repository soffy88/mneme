import pytest
import uuid
from services.main import app, get_current_user
from services.models import User, UserRole, SpeakingSession
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import delete, select
from obase.config import settings
from httpx import AsyncClient, ASGITransport

@pytest.fixture(autouse=True)
def register_mocks():
    from obase.persistence.pool import PgPool
    PgPool.clear()
    
    from obase.provider_registry import ProviderRegistry
    
    class MockASRCaller:
        async def __call__(self, *, audio_b64: str, language: str = "zh", **kwargs):
            return "Yes, this is a mock transcription of the student response."
            
    class MockTTSCaller:
        async def __call__(self, *, text: str, language: str = "en", **kwargs):
            return "dGVzdF9hdWRpb19kYXRh"

    class MockPronunciationCaller:
        async def __call__(self, *, audio_b64: str, reference_text: str, **kwargs):
            from oprim._mneme_speech_types import PronunciationResult
            return PronunciationResult(
                overall_score=0.85,
                fluency_score=0.80,
                accuracy_score=0.90,
                word_scores=[]
            )
            
    class MockLLMCaller:
        async def __call__(self, *, messages: list, max_tokens: int = 1000, **kwargs):
            return {"content": "That is wonderful! Can you tell me more about your plans?", "usage": {"input_tokens": 0, "output_tokens": 0}}

    ProviderRegistry.register("asr", "default", MockASRCaller(), replace=True)
    ProviderRegistry.register("tts", "default", MockTTSCaller(), replace=True)
    ProviderRegistry.register("pronunciation", "aliyun", MockPronunciationCaller(), replace=True)
    ProviderRegistry.register("pronunciation", "default", MockPronunciationCaller(), replace=True)
    ProviderRegistry.register("llm", "default", MockLLMCaller(), replace=True)

@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()

@pytest.fixture(scope="function")
async def student(db):
    sid = uuid.uuid4()
    user = User(
        id=sid,
        phone=f"181{str(sid)[:8]}",
        role=UserRole.student,
        name="Test Student",
        grade="高一"
    )
    db.add(user)
    await db.commit()
    yield user
    await db.execute(delete(SpeakingSession).where(SpeakingSession.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()

@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

@pytest.mark.asyncio
async def test_speaking_practice_returns_encouraging_feedback(client, student):
    # Override FastAPI auth dependency
    app.dependency_overrides[get_current_user] = lambda: student
    
    payload = {
        "topic": "Weekend plans",
        "target_sentences": "I plan to play basketball.",
        "grade": "Grade 10"
    }
    
    try:
        resp = await client.post("/v1/speaking/practice", json=payload)
        if resp.status_code != 200:
            print("DEBUG: status_code =", resp.status_code, "body =", resp.text)
        assert resp.status_code == 200
        
        data = resp.json()
        assert "session_id" in data
        assert "turns" in data
        assert "pronunciation_scores" in data
        assert "overall_progress" in data
        
        turns = data["turns"]
        assert len(turns) > 0
        
        discouraging_words = [
            "you should say",
            "the correct way is",
            "the correct phrase is",
            "it should be",
            "you made a mistake",
            "that is wrong",
            "incorrect"
        ]
        
        # Verify AI feedback is encouraging and has no direct negative correction
        for turn in turns:
            feedback = turn["ai_feedback"].lower()
            for word in discouraging_words:
                assert word not in feedback, f"Feedback '{feedback}' contains discouraging phrase: '{word}'"
    finally:
        app.dependency_overrides = {}

@pytest.mark.asyncio
async def test_speaking_practice_creates_session_record(client, student, db):
    app.dependency_overrides[get_current_user] = lambda: student
    
    payload = {
        "topic": "Daily routine",
        "target_sentences": "I wake up early.",
        "grade": "Grade 10"
    }
    
    try:
        resp = await client.post("/v1/speaking/practice", json=payload)
        if resp.status_code != 200:
            print("DEBUG 2: status_code =", resp.status_code, "body =", resp.text)
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        
        # Verify session is persisted in db
        stmt = select(SpeakingSession).where(SpeakingSession.id == session_id)
        session_record = (await db.execute(stmt)).scalar_one_or_none()
        
        assert session_record is not None
        assert session_record.student_id == student.id
        assert "Daily routine" in session_record.topic
        assert len(session_record.turns) > 0
        assert len(session_record.pronunciation_scores) > 0
        assert session_record.overall_progress > 0
        
        # Verify GET /v1/speaking/history/{student_id} lists it
        history_resp = await client.get(f"/v1/speaking/history/{student.id}")
        assert history_resp.status_code == 200
        history_list = history_resp.json()
        
        assert len(history_list) == 1
        assert history_list[0]["session_id"] == session_id
        assert "Daily routine" in history_list[0]["topic"]
        assert history_list[0]["overall_progress"] == session_record.overall_progress
    finally:
        app.dependency_overrides = {}

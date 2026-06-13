import pytest
import uuid
import asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from services.main import app
from services.models import User, UserRole, KCMastery, InteractionEvent
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from obase.config import settings
from obase.db import get_db

@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.fixture
async def db_session():
    # 为每个测试创建独立的 engine 避免 loop 冲突
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        yield session
    
    await engine.dispose()

@pytest.fixture
async def test_student(db_session):
    student_id = uuid.uuid4()
    user = User(id=student_id, phone=f"150{str(uuid.uuid4())[:8]}", role=UserRole.student)
    db_session.add(user)
    await db_session.commit()
    
    yield student_id
    
    # 清理
    await db_session.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
    await db_session.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
    await db_session.execute(delete(User).where(User.id == student_id))
    await db_session.commit()

@pytest.mark.asyncio
async def test_api_interaction_and_mastery(api_client, test_student):
    payload = {
        "student_id": str(test_student),
        "kc_id": "GDMATH-SET-01",
        "is_correct": True,
        "question_type": "choice"
    }
    response = await api_client.post("/v1/interaction", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["kc_id"] == "GDMATH-SET-01"
    assert data["p_mastery"] > 0.45
    
    response = await api_client.get(f"/v1/mastery/{test_student}")
    assert response.status_code == 200
    mastery_list = response.json()
    assert len(mastery_list) >= 1
    assert mastery_list[0]["kc_id"] == "GDMATH-SET-01"

@pytest.mark.asyncio
async def test_api_kc_endpoints(api_client):
    response = await api_client.get("/v1/kc")
    assert response.status_code == 200
    kc_list = response.json()
    assert len(kc_list) > 0
    
    kc_id = kc_list[0]["kc_id"]
    response = await api_client.get(f"/v1/kc/{kc_id}")
    assert response.status_code == 200
    assert response.json()["kc_id"] == kc_id

@pytest.mark.asyncio
async def test_api_review_queue(api_client, test_student):
    payload = {
        "student_id": str(test_student),
        "kc_id": "GDMATH-SET-01",
        "is_correct": False
    }
    await api_client.post("/v1/interaction", json=payload)
    # 2. 获取复习池 (模拟 1 天后)
    future_now = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = await api_client.get(f"/v1/review-queue/{test_student}", params={"now": future_now})
    if response.status_code != 200:
        print(f"Error Body: {response.text}")
    assert response.status_code == 200
    queue = response.json()
    assert len(queue) >= 1
    assert queue[0]["kc_id"] == "GDMATH-SET-01"


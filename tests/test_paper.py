import pytest
import uuid
import io
from httpx import AsyncClient, ASGITransport
from services.main import app
from services.models import Paper, PaperStatus, User, UserRole
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from obase.config import settings

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.fixture
async def test_student():
    async with SessionLocal() as session:
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"180{str(uuid.uuid4())[:8]}", role=UserRole.student)
        session.add(user)
        await session.commit()
        
        yield student_id
        
        # 清理 (按外键顺序)
        await session.execute(delete(Paper).where(Paper.student_id == student_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()

@pytest.mark.asyncio
async def test_paper_upload(api_client, test_student):
    # 模拟一个文件内容
    file_content = b"fake image content"
    file = io.BytesIO(file_content)
    
    # 上传
    response = await api_client.post(
        f"/v1/papers/upload?student_id={test_student}",
        files={"file": ("test_paper.jpg", file, "image/jpeg")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "paper_id" in data
    assert data["status"] == "processing"
    
    paper_id = data["paper_id"]
    
    # 验证数据库
    async with SessionLocal() as session:
        stmt = select(Paper).where(Paper.id == uuid.UUID(paper_id))
        result = await session.execute(stmt)
        paper = result.scalar_one()
        assert paper.student_id == test_student
        assert paper.status == PaperStatus.processing
        assert "papers/" in paper.image_urls["original"]

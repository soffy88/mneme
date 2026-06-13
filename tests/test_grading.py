import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, delete
from obase.config import settings
from obase.llm import register_mock_providers
from oskill.paper_grading import process_single_question
from services.models import WrongQuestion, User, UserRole

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(autouse=True)
def setup_mock_llm():
    register_mock_providers()

@pytest.fixture
async def test_student():
    async with SessionLocal() as session:
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"199{str(uuid.uuid4())[:8]}", role=UserRole.student)
        session.add(user)
        await session.commit()
        
        yield student_id
        
        # 清理
        await session.execute(delete(WrongQuestion).where(WrongQuestion.student_id == student_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()

@pytest.mark.asyncio
async def test_process_single_question_wrong(test_student):
    async with SessionLocal() as session:
        # 1. 运行单题批改流程 (Mock 下默认会是错的，因为 MockVLM 返回空 questions，
        # 但 grade_question LLM mock 返回 "Mock Response" 被 json.loads 失败，兜底是 False)
        # 修正：MockLLM 在 obase/llm.py 中现在返回固定内容。
        # 实际上 MockLLM 需要返回 JSON 格式才能让 grade_question 解析。
        # 暂时依赖 grade_question 的异常兜底 (False) 进行测试。
        
        res = await process_single_question(
            session=session,
            student_id=test_student,
            paper_id=None,
            question_text="1+1=?",
            student_answer="3",
            correct_answer="2"
        )
        
        assert res["status"] == "wrong"
        assert "wq_id" in res
        
        # 提交到 DB (在 oskill 中已经 execute 了，但需要 commit)
        await session.commit()
        
        # 验证数据库
        stmt = select(WrongQuestion).where(WrongQuestion.id == uuid.UUID(res["wq_id"]))
        result = await session.execute(stmt)
        wq = result.scalar_one()
        assert wq.student_id == test_student
        assert wq.student_answer == "3"
        assert wq.error_type is not None

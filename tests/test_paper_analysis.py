import pytest
import uuid
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from obase.config import settings
from obase.cognitive_store import PgStore
from omodul.analyze_paper import analyze_paper_workflow, AnalyzePaperConfig, AnalyzePaperInput
from services.models import Paper, PaperStatus, User, UserRole, KCMastery, InteractionEvent
from oprim.llm_oprims import PaperOCRResult
from sqlalchemy import select, delete

@pytest.fixture(scope="function")
async def db_context():
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        # 创建一个测试学生
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"136{str(uuid.uuid4())[:8]}", role=UserRole.student)
        session.add(user)
        await session.flush()
        
        # 创建一个测试试卷
        paper_id = uuid.uuid4()
        paper = Paper(id=paper_id, student_id=student_id, status=PaperStatus.processing)
        session.add(paper)
        
        await session.commit()
        
        yield session, student_id, paper_id
        
        # 清理
        await session.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
        await session.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()
    
    await engine.dispose()

@pytest.mark.asyncio
async def test_paper_analysis_updates_mastery(db_context):
    session, student_id, paper_id = db_context
    store = PgStore(session)
    config = AnalyzePaperConfig()
    
    # 模拟 OCR 结果
    mock_ocr_res = PaperOCRResult(
        questions=[
            {"no": "1", "question_text": "1+1=?", "student_answer": "3", "correct_answer": "2"}
        ],
        raw_text="Fake OCR"
    )
    
    # 模拟 process_single_question (oskill)
    mock_grading_res = {
        "status": "wrong",
        "wq_id": str(uuid.uuid4()),
        "error_type": "careless",
        "knowledge_points": ["GDMATH-SET-01"],
        "parent_note": "Careless error"
    }
    
    with patch("omodul.analyze_paper.ocr_paper", AsyncMock(return_value=mock_ocr_res)), \
         patch("omodul.analyze_paper.process_single_question", AsyncMock(return_value=mock_grading_res)):
        
        input_data = AnalyzePaperInput(
            paper_id=paper_id,
            student_id=student_id,
            image_b64_list=["fake_b64"]
        )
        
        # 预热 PriorProvider
        from obase.prior_provider import PriorProvider
        await PriorProvider.warm_up(session)
        
        result = await analyze_paper_workflow(config, input_data, store, session)
        
        assert result["status"] == "completed"
        findings = result["findings"]
        assert findings.wrong_count == 1
        assert len(findings.cognitive_updates) == 1
        assert findings.cognitive_updates[0]["kc_id"] == "GDMATH-SET-01"
        
        # 验证数据库状态
        # 1. 试卷状态应为 done
        stmt = select(Paper).where(Paper.id == paper_id)
        paper = (await session.execute(stmt)).scalar_one()
        assert paper.status == PaperStatus.done
        
        # 2. 应存在 kc_mastery 记录
        stmt = select(KCMastery).where(KCMastery.student_id == student_id, KCMastery.knowledge_point == "GDMATH-SET-01")
        mastery = (await session.execute(stmt)).scalar_one_or_none()
        assert mastery is not None
        assert mastery.n_attempts == 1
        # 因为答错了，p_mastery 应低于或等于 p_init (取决于 BKT 逻辑)
        # 初始 p_init 通常是 0.2 或 0.05 等，答错会下降
        
        # 3. 应存在 InteractionEvent 记录
        stmt = select(InteractionEvent).where(InteractionEvent.student_id == student_id)
        event = (await session.execute(stmt)).scalar_one_or_none()
        assert event is not None
        assert event.knowledge_point == "GDMATH-SET-01"
        assert event.is_correct is False
        assert event.source == "paper"

    print("\n  Task 3.4: Paper analysis -> Cognitive update wiring verified ✓")

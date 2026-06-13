import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from obase.config import settings
from obase.cognitive_store import InMemoryStore, PgStore
from omodul.cognitive import process_interaction_workflow as process_interaction, InteractionConfig, InteractionInput
from services.models import KCMastery, InteractionEvent, User, UserRole
from sqlalchemy import delete

@pytest.fixture(scope="function")
async def db_context():
    # 在 fixture 内部创建 engine，确保它与当前 event loop 绑定
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        # 创建一个测试学生
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"138{str(uuid.uuid4())[:8]}", role=UserRole.student)
        session.add(user)
        await session.commit()
        
        yield session, student_id
        
        # 清理测试数据
        await session.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
        await session.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()
    
    await engine.dispose()

@pytest.mark.asyncio
async def test_store_consistency(db_context):
    session, student_id = db_context
    kc_id = "GDMATH-CONIC-01"
    
    # 预热 PriorProvider 确保一致性
    from obase.prior_provider import PriorProvider
    await PriorProvider.warm_up(session)
    
    in_memory_store = InMemoryStore()
    pg_store = PgStore(session)
    config = InteractionConfig()
    
    now = datetime.now(timezone.utc)
    
    # 交互序列
    interactions = [
        {"is_correct": False, "used_answer": True, "now": now},
        {"is_correct": True, "now": now + timedelta(hours=1)},
        {"is_correct": True, "now": now + timedelta(days=1)},
    ]
    
    for i, interaction in enumerate(interactions):
        # 运行 InMemory
        input_mem = InteractionInput(student_id=student_id, kc_id=kc_id, is_correct=interaction["is_correct"], used_answer=interaction.get("used_answer", False), now=interaction["now"])
        res_mem_dict = await process_interaction(config, input_mem, in_memory_store)
        res_mem = res_mem_dict["findings"]
        
        # 运行 Pg
        input_pg = InteractionInput(student_id=student_id, kc_id=kc_id, is_correct=interaction["is_correct"], used_answer=interaction.get("used_answer", False), now=interaction["now"])
        res_pg_dict = await process_interaction(config, input_pg, pg_store)
        res_pg = res_pg_dict["findings"]
        
        # 比较结果
        assert res_mem.p_mastery == res_pg.p_mastery
        assert res_mem.long_term_mastery == res_pg.long_term_mastery
        assert res_mem.effective_mastery == res_pg.effective_mastery
        assert res_mem.error_type == res_pg.error_type
        assert res_mem.rating == res_pg.rating
        
    print(f"  InMemoryStore 与 PgStore 序列一致性验证通过 ✓")

@pytest.mark.asyncio
async def test_question_type_priors(db_context):
    session, student_id = db_context
    pg_store = PgStore(session)
    config = InteractionConfig()
    
    # 集合知识点 GDMATH-SET-01，支持 choice 和 fill
    # choice 蒙对率应为 0.25，fill 蒙对率应为 0.05
    
    # 1. Choice 交互
    sid_choice = uuid.uuid4()
    # 模拟创建用户
    from services.models import User, UserRole
    user = User(id=sid_choice, phone=f"139{str(uuid.uuid4())[:8]}", role=UserRole.student)
    session.add(user)
    await session.commit()
    
    input_choice = InteractionInput(student_id=sid_choice, kc_id="GDMATH-SET-01", is_correct=False, question_type="choice")
    await process_interaction(config, input_choice, pg_store)
    state_choice, _ = await pg_store.get_or_create(sid_choice, "GDMATH-SET-01", "choice")
    assert state_choice.p_guess == 0.25
    
    # 2. Fill 交互
    sid_fill = uuid.uuid4()
    user2 = User(id=sid_fill, phone=f"137{str(uuid.uuid4())[:8]}", role=UserRole.student)
    session.add(user2)
    await session.commit()
    
    input_fill = InteractionInput(student_id=sid_fill, kc_id="GDMATH-SET-01", is_correct=False, question_type="fill")
    await process_interaction(config, input_fill, pg_store)
    state_fill, _ = await pg_store.get_or_create(sid_fill, "GDMATH-SET-01", "fill")
    assert state_fill.p_guess == 0.05
    
    print("  题型展开先验参数验证通过 ✓")

@pytest.mark.asyncio
async def test_pg_store_persistence(db_context):
    session, student_id = db_context
    kc_id = "GDMATH-SET-01"
    pg_store = PgStore(session)
    config = InteractionConfig()
    
    # 第一次交互
    input1 = InteractionInput(student_id=student_id, kc_id=kc_id, is_correct=True)
    await process_interaction(config, input1, pg_store)
    await session.commit()
    
    # 获取状态
    state1, card1 = await pg_store.get_or_create(student_id, kc_id)
    p1 = state1.p_mastery
    
    # 模拟重新开启 Session
    # 需要使用与 db_context 相同的 engine 避免 loop 冲突，或者再起一个 dispose
    # 这里简单起见，从 session 获取 bind
    engine = session.bind
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session2:
        pg_store2 = PgStore(session2)
        state2, card2 = await pg_store2.get_or_create(student_id, kc_id)
        assert state2.p_mastery == pytest.approx(p1)
        assert card2["stability"] == pytest.approx(card1["stability"])
        
    print("  PgStore 持久化验证通过 ✓")

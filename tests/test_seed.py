"""
B.2 DoD 测试：KC 字典 seed → bkt_priors
=========================================
1. bkt_priors 行数 = KC数 × 题型数（57 行）
2. 重启后幂等（第二次 seed 不新增行）
3. p_guess 按题型正确展开（choice=0.25, fill=0.05, solve=0.02）
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.guangdong_math_kc import KC_LIST
from obase.config import settings
from services.models import BKTPrior
from services.seed import seed_bkt_priors

EXPECTED_ROWS = sum(len(kc.get("question_types", ["solve"])) for kc in KC_LIST)


@pytest.fixture(scope="function")
async def db_session():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_row_count(db_session):
    """seed 后 bkt_priors 行数 = KC数 × 题型数。"""
    await seed_bkt_priors(db_session)
    await db_session.commit()

    count = (await db_session.execute(select(func.count()).select_from(BKTPrior))).scalar_one()
    assert count == EXPECTED_ROWS, (
        f"bkt_priors 应有 {EXPECTED_ROWS} 行 (29 KC × 题型展开)，实际 {count}"
    )
    print(f"  bkt_priors 行数正确: {count} = {len(KC_LIST)} KC × 题型 ✓")


@pytest.mark.asyncio
async def test_seed_idempotent(db_session):
    """连续调用两次 seed，行数不变（幂等 upsert）。"""
    await seed_bkt_priors(db_session)
    await db_session.commit()
    await seed_bkt_priors(db_session)
    await db_session.commit()

    count = (await db_session.execute(select(func.count()).select_from(BKTPrior))).scalar_one()
    assert count == EXPECTED_ROWS, (
        f"重复 seed 后行数应仍为 {EXPECTED_ROWS}，实际 {count}"
    )
    print(f"  幂等验证通过: 两次 seed 后仍 {count} 行 ✓")


@pytest.mark.asyncio
async def test_seed_guess_rates(db_session):
    """choice=0.25, fill=0.05, solve=0.02 的 p_guess 正确写入。"""
    await seed_bkt_priors(db_session)
    await db_session.commit()

    for q_type, expected_guess in [("choice", 0.25), ("fill", 0.05), ("solve", 0.02)]:
        rows = (
            await db_session.execute(
                select(BKTPrior).where(BKTPrior.question_type == q_type)
            )
        ).scalars().all()
        for row in rows:
            assert row.p_guess == pytest.approx(expected_guess), (
                f"{q_type} 题型的 p_guess 应为 {expected_guess}，实际 {row.p_guess}"
            )
    print("  p_guess 按题型展开正确 (choice=0.25, fill=0.05, solve=0.02) ✓")

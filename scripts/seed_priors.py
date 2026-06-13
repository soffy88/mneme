"""
KC 字典种子数据填充脚本
=======================
scripts/seed_priors.py
"""

import asyncio
import uuid
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from obase.config import settings
from services.models import BKTPrior, Base
from data.guangdong_math_kc import KC_LIST

# 题型对应的默认猜测率 (Master §7 & guangdong_math_kc 建议)
GUESS_RATES = {
    "choice": 0.25,
    "fill": 0.05,
    "solve": 0.02
}

async def seed_bkt_priors():
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with Session() as session:
        print(f"开始同步 BKT 先验参数表 (BKTPrior)...")
        
        # 1. 统计当前数据
        result = await session.execute(select(BKTPrior))
        existing_count = len(result.scalars().all())
        print(f"当前表中已有 {existing_count} 条记录。")
        
        # 2. 清理旧数据 (为了保证 seed 的一致性，简单处理)
        await session.execute(delete(BKTPrior))
        
        # 3. 展开并插入
        new_records = []
        for kc in KC_LIST:
            base_bkt = kc["bkt"]
            q_types = kc.get("question_types", ["solve"])
            
            for q_type in q_types:
                # 按照题型调整 p_guess
                p_guess = GUESS_RATES.get(q_type, base_bkt["p_guess"])
                
                record = BKTPrior(
                    id=uuid.uuid4(),
                    subject="math",
                    grade=kc["grade"],
                    knowledge_point=kc["kc_id"],
                    question_type=q_type,
                    p_init=base_bkt["p_init"],
                    p_transit=base_bkt["p_transit"],
                    p_guess=p_guess,
                    p_slip=base_bkt["p_slip"],
                )
                new_records.append(record)
        
        session.add_all(new_records)
        await session.commit()
        
        print(f"同步完成！共插入 {len(new_records)} 条记录 (KC={len(KC_LIST)} × 题型展开)。")
        
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_bkt_priors())

"""CLI: 种子题库导入命令。用法: python -m scripts.seed_question_bank"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from services.seed_question_bank import seed_all


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://mneme:mneme@localhost:5432/mneme",
)


async def main():
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await seed_all(session)
        print("Seed result:", result)

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
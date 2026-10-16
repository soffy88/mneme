"""一键清理 CTSF v1.2.0 导入数据的脚本（按标记删除）。
"""
from __future__ import annotations

import sys
import asyncio

sys.path.insert(0, '/app')

from sqlalchemy import text
from obase.db import SessionLocal

async def remove_ctsf_data():
    print("=== 开始清理 CTSF v1.2.0 导入数据 ===")
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM reading_passages WHERE source_url LIKE 'ctsf%'"))
        await db.execute(text("DELETE FROM question_records WHERE source = 'ctsf-v1.2.0'"))
        await db.execute(text("DELETE FROM knowledge_units WHERE id LIKE 'ctsf-%'"))
        await db.execute(text("DELETE FROM knowledge_clusters WHERE id LIKE 'ctsf-%'"))
        await db.execute(text("DELETE FROM textbooks WHERE id LIKE 'ctsf-%'"))
        await db.commit()
        print("=== 清理完成 ===")

if __name__ == '__main__':
    asyncio.run(remove_ctsf_data())

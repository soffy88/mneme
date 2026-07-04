"""graded_reading_service.py — 分级泛读选文服务（U.19 英语习得型范式）

素养轨（同 oprim.chinese_track 的语文素养轨设计）：只做内容分发 + 复用既有
reading_guide_workflow 做阅读理解引导，不套 BKT/FSRS——泛读读的是"可理解输入"
（i+1），不是要考核掌握度的知识点。

i+1：i = vocab_service.estimate_reading_level（学生词汇掌握度推出的当前水平），
选 difficulty_band == min(i+1, 5) 的文章；该档无文章时退而选最接近的档，不报错。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ReadingPassage


async def select_graded_passage(db: AsyncSession, student_id: uuid.UUID) -> dict:
    """按学生当前词汇水平 i 选 i+1 档分级读物。库中该科目无任何读物时报错。"""
    from services.vocab_service import estimate_reading_level

    i = await estimate_reading_level(db, student_id)
    target_band = min(i + 1, 5)

    row = await _pick_passage_near_band(db, target_band)
    if row is None:
        return {"error": "读物库为空"}

    return {
        "passage_id": row.id,
        "title": row.title,
        "body_text": row.body_text,
        "difficulty_band": row.difficulty_band,
        "target_band": target_band,
        "reading_level_i": i,
        "source_url": row.source_url,
        "license": row.license,
    }


async def _pick_passage_near_band(db: AsyncSession, target_band: int):
    """target_band 精确命中优先；否则按 |band-target| 最近退而求其次。"""
    exact = (
        await db.execute(
            select(ReadingPassage)
            .where(ReadingPassage.difficulty_band == target_band)
            .order_by(ReadingPassage.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if exact is not None:
        return exact

    all_passages = (await db.execute(select(ReadingPassage))).scalars().all()
    if not all_passages:
        return None
    return min(all_passages, key=lambda p: abs(p.difficulty_band - target_band))


__all__ = ["select_graded_passage"]

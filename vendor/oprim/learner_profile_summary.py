"""oprim.learner_profile_summary — L2 Learner Profile generation.

Converts numerical BKT vectors (P(L)) into a natural language description.
This profile is injected into LLM system prompts (e.g. Socratic guiding, Daily Plan)
to provide grounded, human-readable context about the student's mastery.

Version: oprim v1.0.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def generate_learner_profile(
    db: AsyncSession,
    student_id: UUID,
) -> str:
    """Generate a natural language profile summary for the student.

    1. Fetches recent BKT states and KU names.
    2. Categorizes into strong, weak, and learning.
    3. Prompts an LLM to generate a concise summary.
    4. Saves to user_learner_profiles table and returns the text.
    """
    from services.models import KCMastery

    # 1. Fetch current BKT states with KU names
    rows = (
        await db.execute(
            sa_text("""
        SELECT m.knowledge_point, m.p_mastery, m.n_attempts,
               COALESCE(k.name, '未知知识点') as ku_name
        FROM kc_mastery m
        LEFT JOIN knowledge_units k ON k.id = m.knowledge_point
        WHERE m.student_id = :sid AND m.p_mastery IS NOT NULL
        ORDER BY m.updated_at DESC
        LIMIT 100
    """),
            {"sid": student_id},
        )
    ).fetchall()

    if not rows:
        return "该学生目前还没有足够的学习记录，处于初始探索阶段。"

    # Categorize
    strong = []
    weak = []
    learning = []
    bkt_snapshot = {}

    for row in rows:
        ku_id, p, n_att, ku_name = row
        p = float(p)
        bkt_snapshot[ku_id] = p

        desc = f"{ku_name} (P(L)={p:.2f})"
        if p >= 0.75:
            strong.append(desc)
        elif p <= 0.40:
            weak.append(desc)
        else:
            learning.append(desc)

    # 2. Build Prompt
    prompt = f"""请根据以下知识追踪（BKT）数据，用一段话（不超过 100 字）总结该学生的学习画像：
强项：{", ".join(strong[:10]) if strong else "无"}
弱项：{", ".join(weak[:10]) if weak else "无"}
发展区：{", ".join(learning[:10]) if learning else "无"}

要求：
1. 语言自然、专业，像老师在做交接。
2. 指出薄弱点（如「弱于...」）和优势（如「擅长...」）。
3. 如果数据很少，只需简单概括。
"""

    # 3. Call LLM
    from services.textbook_qa_service import _get_caller

    try:
        caller = _get_caller()
        result = await caller(
            messages=[{"role": "user", "content": prompt}],
            system="你是一位资深的教学教研专家。请生成学生的学习画像摘要，不要寒暄，直接输出摘要正文。",
            max_tokens=150,
        )
        profile_text = result.get("content", "").strip()
    except Exception as e:
        logger.warning("generate_learner_profile LLM error: %s", e)
        profile_text = f"学生有 {len(strong)} 个强项知识点，{len(weak)} 个薄弱知识点。"

    # 4. Save to DB
    now = datetime.now(timezone.utc)
    import json

    # Check if exists to increment version
    existing = (
        await db.execute(
            sa_text(
                "SELECT version FROM user_learner_profiles WHERE student_id = :sid"
            ),
            {"sid": student_id},
        )
    ).scalar_one_or_none()

    if existing is not None:
        await db.execute(
            sa_text("""
            UPDATE user_learner_profiles 
            SET profile_text = :text, bkt_snapshot = :snap, generated_at = :now, version = version + 1
            WHERE student_id = :sid
        """),
            {
                "text": profile_text,
                "snap": json.dumps(bkt_snapshot),
                "now": now,
                "sid": student_id,
            },
        )
    else:
        await db.execute(
            sa_text("""
            INSERT INTO user_learner_profiles (student_id, profile_text, bkt_snapshot, generated_at, version)
            VALUES (:sid, :text, :snap, :now, 1)
        """),
            {
                "sid": student_id,
                "text": profile_text,
                "snap": json.dumps(bkt_snapshot),
                "now": now,
            },
        )
    await db.commit()

    return profile_text


async def get_latest_learner_profile(db: AsyncSession, student_id: UUID) -> str:
    """Read the latest cached profile, or generate if none exists."""
    row = (
        await db.execute(
            sa_text(
                "SELECT profile_text FROM user_learner_profiles WHERE student_id = :sid"
            ),
            {"sid": student_id},
        )
    ).scalar_one_or_none()

    if row:
        return row

    # Generate synchronously here if it doesn't exist
    return await generate_learner_profile(db, student_id)

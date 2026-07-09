"""textbook_bindings_service.py — N.4 用户教材绑定

同 daily_plan_prefs_service.py 的 get/set 模式：偏好存 users.textbook_bindings
（JSONB，{subject: textbook_id}）。跟 daily_plan_prefs 的区别：这里的白名单不是
"允许哪些 key"，而是"允许哪些学科(subject)"，且每个值还要校验"这个 textbook_id
真的存在且属于该学科"（否则 daily_plan_service 拿着一个查不到的 id 过滤，会让
该学科新知识点推荐悄悄清零）。

未绑定学科 = 该 key 不存在于 JSONB 里 = daily_plan_service 回退今天"该学科全部
教材混排"的行为，向后兼容，不强制旧用户补填。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Textbook, User

_ALLOWED_SUBJECTS = {"math", "physics", "chinese", "english"}


async def get_textbook_bindings(db: AsyncSession, student_id: uuid.UUID) -> dict:
    row = (
        await db.execute(select(User.textbook_bindings).where(User.id == student_id))
    ).scalar_one_or_none()
    return dict(row or {})


async def set_textbook_bindings(
    db: AsyncSession, student_id: uuid.UUID, updates: dict
) -> dict:
    """合并写入（部分更新，未传的学科保留原值）；值为 None 表示清除该学科绑定。
    未知学科拒绝；非 None 的 textbook_id 必须在 textbooks 表存在且 subject 匹配，
    否则拒绝（避免存进去一个查不到/学科不匹配的 id，daily_plan_service 悄悄按它
    过滤出空结果）。
    """
    unknown = set(updates) - _ALLOWED_SUBJECTS
    if unknown:
        return {"error": f"未知学科: {sorted(unknown)}"}

    for subject, tb_id in updates.items():
        if tb_id is None:
            continue
        tb = (
            await db.execute(select(Textbook).where(Textbook.id == tb_id))
        ).scalar_one_or_none()
        if tb is None:
            return {"error": f"教材不存在: {tb_id}"}
        if tb.subject != subject:
            return {"error": f"教材 {tb_id} 属于 {tb.subject}，不是 {subject}"}

    current = await get_textbook_bindings(db, student_id)
    merged = {**current, **updates}
    # None 值代表"清除该学科绑定"，不应该留在 JSONB 里占位
    merged = {k: v for k, v in merged.items() if v is not None}

    await db.execute(
        update(User).where(User.id == student_id).values(textbook_bindings=merged)
    )
    await db.commit()
    return merged

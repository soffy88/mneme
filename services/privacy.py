"""L6 · 青少年隐私分层。

结果数据（进度/掌握/连续/出勤）家长默认可见；**过程数据**（具体错什么、情绪信号、求助/苏格拉底
记录）归学生：<12 岁监护优先家长可见，12 岁以上默认**不可见**、可协商开放（`share_process_with_parent`）。
依据：青少年自主性与过程隐私（与 SDT 自主需求一致，避免监控反噬）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import User

_YOUNG_AGE = 12  # 12 岁以下：监护优先，过程数据家长可见


def _age(birth_date: date | None) -> int | None:
    if birth_date is None:
        return None
    today = datetime.now(timezone.utc).date()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


async def parent_sees_process(db: AsyncSession, accessor: User, student_id) -> bool:
    """访问者能否看该生**过程数据**。

    - 本人 → 能。
    - 家长 → 该生 <12 岁（监护）或已协商开放（share_process_with_parent）才能；否则不能。
    """
    if accessor.id == student_id:
        return True
    row = (
        await db.execute(
            select(User.birth_date, User.share_process_with_parent).where(
                User.id == student_id
            )
        )
    ).first()
    if row is None:
        return False
    birth_date, shared = row
    age = _age(birth_date)
    if age is not None and age < _YOUNG_AGE:
        return True  # 低龄：监护优先
    return bool(shared)

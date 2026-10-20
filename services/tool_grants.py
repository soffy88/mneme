"""服务层工具授权：在 W5 Part B ``obase.user_grants`` 之上加「学生默认工具集」。

``obase.user_grants`` 是 vendor 只读件，语义不动：``agent.user_grants`` 行由 admin 经
``SetUserGrant`` 写，``enabled_tools`` 为显式白名单。本模块只决定**没有授权行（或
enabled_tools 为 NULL）时**的默认：

- admin（``ADMIN_USER_IDS``）→ 一律放行；
- 有显式 ``enabled_tools`` → 以 admin 白名单为准（可借此给个别学生撤销默认工具）；
- 无授权行 → 仅 ``role=student`` 本人对 ``DEFAULT_STUDENT_TOOLS`` 放行，其余拒绝
  （家长/未知角色、以及 BindPartnerChannel 这类特权工具仍 deny-by-default）。

默认集只收「只读共享知识图 / 无状态、掌握度仍只经 SubmitAnswer 写」的工具。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

# 先修回溯诊断（cn-math-taxonomy）——tutor agent 默认可用
PREREQ_DIAGNOSIS_TOOLS: frozenset[str] = frozenset(
    {"SearchMathTopic", "GetMathTopic", "StartPrereqDiagnosis", "SubmitPrereqDiagnosisAnswer"}
)
DEFAULT_STUDENT_TOOLS: frozenset[str] = PREREQ_DIAGNOSIS_TOOLS


def _is_student(user: Any) -> bool:
    role = getattr(user, "role", None)
    return str(getattr(role, "value", role)) == "student"


async def is_tool_allowed(db: AsyncSession, user: Any, tool_name: str) -> bool:
    from obase.admin_identity import is_admin
    from obase.user_grants import get_grant

    if is_admin(user):
        return True
    student_id: UUID = user.id
    grant = await get_grant(db, student_id)
    enabled = grant.get("enabled_tools")
    if enabled is not None:
        return tool_name in enabled
    return _is_student(user) and tool_name in DEFAULT_STUDENT_TOOLS

"""obase.admin_identity — W5 Part B：admin 身份判定。

用户拍板：多用户「admin 授权」需要 admin 概念，但原 mneme 账号体系零改动——
User/UserRole 表不碰（现在只有 student/parent）。改用 ADMIN_USER_IDS 环境变量
白名单（逗号分隔 UUID），纯函数判定，零 schema 改动。
"""

from __future__ import annotations

import os
from uuid import UUID


def _admin_ids_from_env() -> frozenset[str]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def is_admin_id(user_id: UUID) -> bool:
    return str(user_id) in _admin_ids_from_env()


def is_admin(user: object) -> bool:
    """便捷封装：接受任意带 `.id` 属性的对象（如 services.models.User），
    避免调用方到处手写 `is_admin_id(user.id)`。"""
    return is_admin_id(getattr(user, "id"))

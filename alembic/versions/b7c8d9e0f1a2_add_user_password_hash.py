"""add password_hash to users (可选密码登录)

Revision ID: b7c8d9e0f1a2
Revises: c3d4e5f6a7b9
Create Date: 2026-10-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """users.password_hash：bcrypt 哈希（可空）。

    可空是刻意的：既有账号全部走手机/邮箱验证码登录，password_hash IS NULL
    表示"未设密码"，登录时回落 OTP，不回落到"空密码可登录"。255 足够放
    bcrypt 的 60 字符输出并留余量。

    合规：这是 users 表的一个列而非新表，purge_service 直接硬删 users 行
    (services/purge_service.py:224)，哈希随之删除，无需新增 _STUDENT_TABLES 条目。
    """
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")

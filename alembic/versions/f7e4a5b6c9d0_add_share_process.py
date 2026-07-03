"""add share_process_with_parent to users (L6 隐私分层)

Revision ID: f7e4a5b6c9d0
Revises: f6d3e4a5b8c9
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7e4a5b6c9d0"
down_revision: Union[str, Sequence[str], None] = "f6d3e4a5b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """users.share_process_with_parent：青少年隐私分层——过程数据(具体错题/情绪/求助)默认归学生
    (False)，12 岁以上可协商向家长开放；结果数据(进度/掌握)不受此限，家长默认可见。"""
    op.add_column(
        "users",
        sa.Column(
            "share_process_with_parent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "share_process_with_parent")

"""add exam_date to users (pedagogy 06 · 考期感知)

Revision ID: f6d3e4a5b8c9
Revises: f5c2d3e4a6b7
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6d3e4a5b8c9"
down_revision: Union[str, Sequence[str], None] = "f5c2d3e4a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """users.exam_date：考试日期（可空）。用于考期感知调度——临近考试压缩复习、
    停推新知（分布式练习向巩固倾斜）。模型早已声明，此为补齐 DB 列。"""
    op.add_column("users", sa.Column("exam_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "exam_date")

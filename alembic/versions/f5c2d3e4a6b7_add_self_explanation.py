"""add self_explanation to interaction_events (pedagogy 04)

Revision ID: f5c2d3e4a6b7
Revises: f4b1c2d3e5a6
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5c2d3e4a6b7"
down_revision: Union[str, Sequence[str], None] = "f4b1c2d3e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """interaction_events.self_explanation：学生自我解释文本（Chi 自我解释效应）。
    只增不改（永久档案红线）；纯采集，不参与判分/掌握度计算。"""
    op.add_column(
        "interaction_events",
        sa.Column("self_explanation", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interaction_events", "self_explanation")

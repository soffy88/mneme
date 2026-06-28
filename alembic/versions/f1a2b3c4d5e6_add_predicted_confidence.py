"""add predicted_confidence to interaction_events (JOL 校准)

Revision ID: f1a2b3c4d5e6
Revises: d049051a89f6
Create Date: 2026-06-28

JOL（Judgment of Learning）：记录作答前学生自评的把握度 ∈[0,1]，
与实际对错对比算校准（Brier / 过度自信）。只增不改的事件日志的一部分。
仅加一列，不触碰其它既有 model↔DB 漂移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd049051a89f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interaction_events', sa.Column('predicted_confidence', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('interaction_events', 'predicted_confidence')

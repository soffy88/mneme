"""add fire_credit source and fire_meta

Revision ID: a3c9e51fb217
Revises: 75da13d304e9
Create Date: 2026-07-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3c9e51fb217"
down_revision: Union[str, Sequence[str], None] = "75da13d304e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: FIRe-lite（T.5，Master §4.8）——interactionsource 加
    'fire_credit' 值 + interaction_events.fire_meta（回写记账：触发交互 id、
    κ、顺延前后 due，nullable）。"""
    # PG12+ 允许在事务内 ADD VALUE（同事务内不使用该值即可）
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'fire_credit'")
    op.add_column(
        "interaction_events",
        sa.Column("fire_meta", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema。PostgreSQL 不支持删 enum value，'fire_credit' 留存无害。"""
    op.drop_column("interaction_events", "fire_meta")

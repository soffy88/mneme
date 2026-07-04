"""add nonmath interaction sources

Revision ID: 2b3c4d5e6f7a
Revises: 4bc93a14fea8
Create Date: 2026-07-04

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "4bc93a14fea8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: T.10 非数学接入认知主线——interactionsource 加
    'force_analysis'/'reading_guide'/'speaking' 三个值。"""
    # PG12+ 允许在事务内 ADD VALUE（同事务内不使用该值即可）
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'force_analysis'")
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'reading_guide'")
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'speaking'")


def downgrade() -> None:
    """Downgrade schema。PostgreSQL 不支持删 enum value，三个值留存无害。"""
    pass

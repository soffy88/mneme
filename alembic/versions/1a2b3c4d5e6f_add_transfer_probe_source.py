"""add transfer_probe source

Revision ID: 1a2b3c4d5e6f
Revises: 00fd98e3ad80
Create Date: 2026-07-04

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "00fd98e3ad80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: U.18 迁移探针——interactionsource 加 'transfer_probe' 值。"""
    # PG12+ 允许在事务内 ADD VALUE（同事务内不使用该值即可）
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'transfer_probe'")


def downgrade() -> None:
    """Downgrade schema。PostgreSQL 不支持删 enum value，'transfer_probe' 留存无害。"""
    pass

"""add_guide_session_modes

Revision ID: c8a2f31e9d05
Revises: dd79083265b7
Create Date: 2026-06-21

添加 SocraticMode enum 新值：force_analysis / reading_guide
供受力分析引导和阅读理解引导会话复用 socratic_sessions 表。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c8a2f31e9d05'
down_revision: Union[str, Sequence[str], None] = 'dd79083265b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres ADD VALUE IF NOT EXISTS requires PG ≥ 9.3; cannot be rolled back in a txn.
    # Use COMMIT trick to run outside transaction.
    op.execute("ALTER TYPE socraticmode ADD VALUE IF NOT EXISTS 'force_analysis'")
    op.execute("ALTER TYPE socraticmode ADD VALUE IF NOT EXISTS 'reading_guide'")


def downgrade() -> None:
    # Postgres cannot remove enum values; downgrade is a no-op.
    pass

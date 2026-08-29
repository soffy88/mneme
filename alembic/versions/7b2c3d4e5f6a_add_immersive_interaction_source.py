"""add immersive interaction source

Revision ID: 7b2c3d4e5f6a
Revises: 6a1b2c3d4e5f
Create Date: 2026-08-29

"""

from typing import Sequence, Union

from alembic import op

revision: str = "7b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "6a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow immersive practice evidence to enter process_interaction."""
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'immersive'")


def downgrade() -> None:
    """PostgreSQL cannot drop enum values; leave 'immersive' in place."""
    pass

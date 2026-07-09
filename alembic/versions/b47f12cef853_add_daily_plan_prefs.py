"""add_daily_plan_prefs

Revision ID: b47f12cef853
Revises: 7a8b9c0d1e2f
Create Date: 2026-07-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b47f12cef853"
down_revision: Union[str, Sequence[str], None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # V.2 每日计划参数可见+可配置：users 加 daily_plan_prefs 列（同 accessibility_prefs 写法）。
    op.add_column(
        "users",
        sa.Column(
            "daily_plan_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "daily_plan_prefs")

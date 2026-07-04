"""add_accessibility_prefs

Revision ID: 890189c51106
Revises: 75cc7c17edbe
Create Date: 2026-07-04 10:34:59.147066

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "890189c51106"
down_revision: Union[str, Sequence[str], None] = "75cc7c17edbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # U.23 UDL 无障碍：users 加 accessibility_prefs 列。
    # 注：autogenerate 还检测出大量与本改动无关的既有模型/DB 漂移（已知问题，
    # 见 audit-fix/p2-14），本迁移只保留这一列，其余不动，不顺手修。
    op.add_column(
        "users",
        sa.Column(
            "accessibility_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "accessibility_prefs")

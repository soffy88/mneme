"""add_mastery_confirmed

Revision ID: 00fd98e3ad80
Revises: f7e4a5b6c9d0
Create Date: 2026-07-04 02:35:05.710133

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "00fd98e3ad80"
down_revision: Union[str, Sequence[str], None] = "f7e4a5b6c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # U.17 掌握裁决题池隔离：与 BKT p_mastery 分离的独立裁决状态。
    # 注：autogenerate 还检测出大量与本改动无关的既有模型/DB 漂移（已知问题，
    # 见 audit-fix/p2-14），本迁移只保留 kc_mastery 这两列，其余不动，不顺手修。
    op.add_column(
        "kc_mastery",
        sa.Column(
            "mastery_confirmed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "kc_mastery",
        sa.Column("mastery_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("kc_mastery", "mastery_confirmed_at")
    op.drop_column("kc_mastery", "mastery_confirmed")

"""add_ku_exam_region_and_edition_variant

Revision ID: 4bc93a14fea8
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-04 04:16:08.670903

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4bc93a14fea8"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # U.21 骨架：中高考区域变体标签 + 教材版本适配层骨架。
    # 注：autogenerate 还检测出大量与本改动无关的既有模型/DB 漂移（已知问题，
    # 见 audit-fix/p2-14），本迁移只保留 knowledge_units 这两列，其余不动，不顺手修。
    op.add_column(
        "knowledge_units",
        sa.Column(
            "exam_region_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_units",
        sa.Column("textbook_edition_variant_of", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("knowledge_units", "textbook_edition_variant_of")
    op.drop_column("knowledge_units", "exam_region_tags")

"""add teaching_figure_specs

教学图规格合同的持久化（teachable-figures 方法论的 Mneme 干净实现，
方法可学，代码自己写）：

- teaching_figure_specs：规格 slug 主键 + 锚点 KU id + 规格全文
  JSONB + verified（默认 False，只由服务端 verify 门禁设置）+
  作者 + 时间戳。ku_id 不设 ORM 外键（同 KnowledgeUnit.textbook_id
  的 DB-level only 惯例，锚点存在性由 verify 门禁在应用层核验）。

Revision ID: tfg1a2b3c4d5e
Revises: f9a1b2c3d4e5
Create Date: 2026-10-31

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'tfg1a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'f9a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teaching_figure_specs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("ku_id", sa.String(100), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_teaching_figure_specs_ku_id", "teaching_figure_specs", ["ku_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_teaching_figure_specs_ku_id", table_name="teaching_figure_specs")
    op.drop_table("teaching_figure_specs")

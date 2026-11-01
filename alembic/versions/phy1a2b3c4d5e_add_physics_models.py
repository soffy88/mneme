"""add physics_models + physics_practice_items

物理真值模型与计算题纪律的持久化（Atlas of Physics 的 model→checks
方法论的 Mneme 干净实现，方法可学，代码自己写）：

- physics_models：模型 slug 主键 + 可选锚点 KU id + 规格全文
  JSONB + verified（默认 False，只由服务端 verify 门禁设置）+
  作者 + 时间戳。ku_id 不设 ORM 外键（同 teaching_figure_specs
  惯例，锚点存在性由 verify 门禁在应用层核验）。
- physics_practice_items：题项 slug 主键 + 模型名（注册表键，
  非 FK）+ 题项全文 JSONB + verified + 作者 + 时间戳。

Revision ID: phy1a2b3c4d5e
Revises: tfg1a2b3c4d5e
Create Date: 2026-11-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'phy1a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'wnb1a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "physics_models",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("ku_id", sa.String(100), nullable=True),
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
        "ix_physics_models_ku_id", "physics_models", ["ku_id"]
    )
    op.create_table(
        "physics_practice_items",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("model_id", sa.String(100), nullable=False),
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
        "ix_physics_practice_items_model_id", "physics_practice_items", ["model_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_physics_practice_items_model_id", table_name="physics_practice_items"
    )
    op.drop_table("physics_practice_items")
    op.drop_index("ix_physics_models_ku_id", table_name="physics_models")
    op.drop_table("physics_models")

"""add_rich_content_to_knowledge_units

为 knowledge_units 添加 rich_content JSONB 列，存储 LLM 生成的"讲透"内容。
可空，幂等更新（IS NULL 则跳过已生成的）。

Revision ID: e7f3a9c21b04
Revises: b1e7d4f2c9a5
Create Date: 2026-06-23
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e7f3a9c21b04'
down_revision: Union[str, Sequence[str], None] = 'b1e7d4f2c9a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'knowledge_units',
        sa.Column('rich_content', JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('knowledge_units', 'rich_content')

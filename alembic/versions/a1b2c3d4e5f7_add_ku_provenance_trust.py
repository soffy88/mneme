"""add_ku_provenance_trust (item 2: 提取可信度/源-AI 分离)

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 提取可信度：溯源 + 源/AI 内容分离 + 校验标志（防 AI 幻觉污染知识库）
    op.add_column('knowledge_units', sa.Column('provenance', JSONB, nullable=True))
    op.add_column('knowledge_units', sa.Column('source_excerpt', sa.Text(), nullable=True))
    op.add_column('knowledge_units', sa.Column(
        'ai_generated', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'verified', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_index('ix_ku_verified', 'knowledge_units', ['verified'])


def downgrade() -> None:
    op.drop_index('ix_ku_verified', table_name='knowledge_units')
    op.drop_column('knowledge_units', 'verified')
    op.drop_column('knowledge_units', 'ai_generated')
    op.drop_column('knowledge_units', 'source_excerpt')
    op.drop_column('knowledge_units', 'provenance')

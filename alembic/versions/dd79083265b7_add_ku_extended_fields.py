"""add_ku_extended_fields

Revision ID: dd79083265b7
Revises: dff2ec15ff91
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'dd79083265b7'
down_revision: Union[str, Sequence[str], None] = 'dff2ec15ff91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── knowledge_units: 补全 AII 接口契约字段 ──────────────────
    op.add_column('knowledge_units', sa.Column(
        'prerequisites', JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'related_kus', JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'difficulty', sa.Float(), server_default=sa.text('0.5'), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'exam_frequency', sa.String(10), server_default=sa.text("'mid'"), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'question_types', JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'ku_type', sa.String(20), server_default=sa.text("'concept'"), nullable=False))
    op.add_column('knowledge_units', sa.Column(
        'curriculum_standard', sa.Text(), nullable=True))
    op.add_column('knowledge_units', sa.Column(
        'mastery_levels', JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))

    # ── 查询索引 ──────────────────────────────────────────────────
    op.create_index('ix_ku_cluster_id',  'knowledge_units',  ['cluster_id'])
    op.create_index('ix_ku_textbook_id', 'knowledge_units',  ['textbook_id'])
    op.create_index('ix_kc_textbook_id', 'knowledge_clusters', ['textbook_id'])


def downgrade() -> None:
    op.drop_index('ix_kc_textbook_id', table_name='knowledge_clusters')
    op.drop_index('ix_ku_textbook_id', table_name='knowledge_units')
    op.drop_index('ix_ku_cluster_id',  table_name='knowledge_units')
    op.drop_column('knowledge_units', 'mastery_levels')
    op.drop_column('knowledge_units', 'curriculum_standard')
    op.drop_column('knowledge_units', 'ku_type')
    op.drop_column('knowledge_units', 'question_types')
    op.drop_column('knowledge_units', 'exam_frequency')
    op.drop_column('knowledge_units', 'difficulty')
    op.drop_column('knowledge_units', 'related_kus')
    op.drop_column('knowledge_units', 'prerequisites')

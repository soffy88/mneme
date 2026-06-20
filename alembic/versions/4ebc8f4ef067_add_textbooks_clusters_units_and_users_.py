"""add_textbooks_clusters_units_and_users_textbook_id

Revision ID: 4ebc8f4ef067
Revises: be949dd2c0d0
Create Date: 2026-06-20 20:41:41.737880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ebc8f4ef067'
down_revision: Union[str, Sequence[str], None] = 'be949dd2c0d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. 新建三张知识体系表 ──────────────────────────────────────
    op.create_table(
        'textbooks',
        sa.Column('id',         sa.String(50),  primary_key=True),
        sa.Column('subject',    sa.String(20),  nullable=False),
        sa.Column('grade',      sa.String(10),  nullable=False),
        sa.Column('edition',    sa.String(30),  nullable=False),
        sa.Column('book_name',  sa.String(100), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'knowledge_clusters',
        sa.Column('id',            sa.String(80),  primary_key=True),
        sa.Column('textbook_id',   sa.String(50),  nullable=False),
        sa.Column('name',          sa.String(100), nullable=False),
        sa.Column('display_order', sa.Integer(),   server_default=sa.text('0')),
        sa.Column('description',   sa.Text()),
        sa.ForeignKeyConstraint(['textbook_id'], ['textbooks.id'],
                                name='fk_kc_textbook'),
    )

    op.create_table(
        'knowledge_units',
        sa.Column('id',           sa.String(100), primary_key=True),
        sa.Column('textbook_id',  sa.String(50),  nullable=False),
        sa.Column('cluster_id',   sa.String(80),  nullable=False),
        sa.Column('name',         sa.String(200), nullable=False),
        sa.Column('description',  sa.Text()),
        sa.ForeignKeyConstraint(['textbook_id'], ['textbooks.id'],
                                name='fk_ku_textbook'),
        sa.ForeignKeyConstraint(['cluster_id'], ['knowledge_clusters.id'],
                                name='fk_ku_cluster'),
    )

    # ── 2. users 表新增 textbook_id（允许 NULL） ──────────────────
    op.add_column(
        'users',
        sa.Column('textbook_id', sa.String(50), nullable=True),
    )
    op.create_foreign_key(
        'fk_users_textbook',
        'users', 'textbooks',
        ['textbook_id'], ['id'],
    )

    # ── 3. 清空旧 GDMATH-* KC粒度数据（废弃，已确认） ─────────────
    op.execute("DELETE FROM kc_mastery        WHERE knowledge_point LIKE 'GDMATH-%'")
    op.execute("DELETE FROM bkt_priors        WHERE knowledge_point LIKE 'GDMATH-%'")
    op.execute("DELETE FROM interaction_events WHERE knowledge_point LIKE 'GDMATH-%'")
    op.execute("DELETE FROM mastery_snapshots  WHERE knowledge_point LIKE 'GDMATH-%'")


def downgrade() -> None:
    op.drop_constraint('fk_users_textbook', 'users', type_='foreignkey')
    op.drop_column('users', 'textbook_id')
    op.drop_table('knowledge_units')
    op.drop_table('knowledge_clusters')
    op.drop_table('textbooks')

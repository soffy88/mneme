"""add user learner profiles for L2 memory

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-14

user_learner_profiles: 存储基于 BKT 的自然语言摘要（L2 记忆）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_learner_profiles',
        sa.Column('student_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('profile_text', sa.Text, nullable=False),          # L2 语言描述
        sa.Column('bkt_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True), # 对应时刻的 BKT 快照，判断是否需要更新
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('version', sa.Integer, server_default='1', nullable=False)
    )
    op.create_foreign_key('fk_ulp_student', 'user_learner_profiles', 'users', ['student_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_table('user_learner_profiles')

"""add_fsrs_weights (FSRS 权重个性化基础设施)

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fsrs_weights',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('cohort', sa.String(50), nullable=False),
        sa.Column('parameters', JSONB, nullable=True),
        sa.Column('logloss', sa.Float(), nullable=True),
        sa.Column('n_reviews', sa.Integer(), server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('cohort', name='uq_fsrs_weights_cohort'),
    )


def downgrade() -> None:
    op.drop_table('fsrs_weights')

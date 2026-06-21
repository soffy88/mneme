"""add ku_match_meta to wrong_questions

Revision ID: 54bdd75b827d
Revises: 3a1f8b920c47
Create Date: 2026-06-21 14:22:11.494228

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '54bdd75b827d'
down_revision: Union[str, Sequence[str], None] = '3a1f8b920c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'wrong_questions',
        sa.Column('ku_match_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('wrong_questions', 'ku_match_meta')

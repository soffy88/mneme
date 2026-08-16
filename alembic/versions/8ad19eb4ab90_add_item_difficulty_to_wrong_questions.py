"""add item_difficulty to wrong_questions

Revision ID: 8ad19eb4ab90
Revises: f0a1b2c3d4e5
Create Date: 2026-08-16 08:20:00.000000

question-bank 的 ZPD 难度自适应排序（services/routers/practice.py）引用了
WrongQuestion.item_difficulty，但该列从未建过——分支一旦命中即 AttributeError。
本迁移补齐 nullable 列：未校准(NULL)按 999.0 距离兜底，无需数据回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8ad19eb4ab90'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wrong_questions', sa.Column('item_difficulty', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('wrong_questions', 'item_difficulty')

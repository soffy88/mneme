"""add_has_text_layer_to_textbook_files

Revision ID: 3a1f8b920c47
Revises: c8a2f31e9d05
Create Date: 2026-06-21

教材导入：textbook_files 表新增 has_text_layer 布尔列，
标记 PDF 是否含可提取文本层（影响阅读器高亮功能可用性）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '3a1f8b920c47'
down_revision: Union[str, Sequence[str], None] = 'c8a2f31e9d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'textbook_files',
        sa.Column('has_text_layer', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('textbook_files', 'has_text_layer')

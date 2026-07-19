"""add char_start/char_end to textbook_chunks (W3 A1 provenance)

Revision ID: a2b3c4d5e6f7
Revises: f7a8b9c0d1e2
Create Date: 2026-07-18

textbook_chunks 补 char_start/char_end：块在所在页（strip 后文本）里的字符偏移
区间 [char_start, char_end)。page_number/section_title 已有页级出处，此二列补
页内定位精度——Book Engine 引用教材原文需要能回指到具体字符区间，不只是页码。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "a2b3c4d5e6f7"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("textbook_chunks", sa.Column("char_start", sa.Integer, nullable=True))
    op.add_column("textbook_chunks", sa.Column("char_end", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("textbook_chunks", "char_end")
    op.drop_column("textbook_chunks", "char_start")

"""books.requested_by：活书编译入口（POST /v1/books/compile）的发起人

Revision ID: bkc1a2b3c4d5
Revises: pep1a2b3c4d5e
Create Date: 2026-10-11

活书编译每本约 $0.5，入口要做 per-user 每日限额 + 全站每日成本上限，必须知道
「这本书是谁发起编译的」。books 原表（d5e6f7a8b9c1）只有 textbook 维度，书本身是
全体学生共享内容，所以只加一个可空列：老书/离线脚本编的书为 NULL，不受影响。
"""

from alembic import op
import sqlalchemy as sa

revision = "bkc1a2b3c4d5"
down_revision = "pep1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("requested_by", sa.String(50), nullable=True))
    op.create_index(
        "ix_books_requested_by_created", "books", ["requested_by", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_books_requested_by_created", table_name="books")
    op.drop_column("books", "requested_by")

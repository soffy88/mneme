"""add book engine tables: books/book_chapters/book_blocks (W3 Part B B3)

Revision ID: d5e6f7a8b9c1
Revises: c4d5e6f7a8ba
Create Date: 2026-07-19

一本书共享给所有学生（不按 student_id 存），B1(ideation/spine)+B2(block
generators) 的编译结果持久化在这三张表。decision_trail/report 仍按既有
omodul 惯例写文件到 output_dir（不进 DB），DB 只存 fingerprint/cost_usd 等
摘要字段——同 vendor/omodul/_base.py build_result() 的既有约定。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "d5e6f7a8b9c1"
down_revision = "c4d5e6f7a8ba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "textbook_id",
            sa.String(50),
            sa.ForeignKey("textbooks.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("target_level", sa.String(50), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="compiling"
        ),  # compiling|ready|error
        sa.Column("fingerprint", sa.String(24), nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("decision_trail_path", sa.Text, nullable=True),
        sa.Column("report_path", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_books_textbook_id", "books", ["textbook_id"])

    op.create_table(
        "book_chapters",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "book_id",
            sa.String(50),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("display_order", sa.Integer, nullable=False),
        sa.Column("cluster_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "learning_objectives", postgresql.JSONB, nullable=False, server_default="[]"
        ),
        sa.Column(
            "prerequisites", postgresql.JSONB, nullable=False, server_default="[]"
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_book_chapters_book_id", "book_chapters", ["book_id"])
    op.create_index(
        "ix_book_chapters_book_order", "book_chapters", ["book_id", "display_order"]
    )

    op.create_table(
        "book_blocks",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "chapter_id",
            sa.String(50),
            sa.ForeignKey("book_chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("block_type", sa.String(20), nullable=False),
        sa.Column("display_order", sa.Integer, nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        # 引用教材的块（text/callout/figure）每条引用的三态（R3/R4）+ 挂接分
        # 单独落一列，供前端/审计直接查——不用每次解析 payload 里的 citations。
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_book_blocks_chapter_id", "book_blocks", ["chapter_id"])
    op.create_index(
        "ix_book_blocks_chapter_order", "book_blocks", ["chapter_id", "display_order"]
    )


def downgrade() -> None:
    op.drop_table("book_blocks")
    op.drop_table("book_chapters")
    op.drop_table("books")

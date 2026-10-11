"""reading_positions：沉浸式阅读的每人阅读位置

Revision ID: rdp1a2b3c4d5
Revises: nbk1a2b3c4d5
Create Date: 2026-10-11

/studio/book 沉浸阅读模式一次只显示一个内容块，需要记住学生读到第几块，
下次打开接着读。来源两种：编译好的活书（source_kind=book, source_id=books.id）与
没有活书时直接读教材原文分块（source_kind=textbook, source_id=textbooks.id）。

只是阅读进度，不是学习证据：不进 kc_mastery / gate.*，不影响任何门控。
student_id 关联未成年人 → 同 PR 入 purge_service._STUDENT_TABLES。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "rdp1a2b3c4d5"
down_revision = "nbk1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reading_positions",
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.String(64), nullable=True),
        sa.Column("total_blocks", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("student_id", "source_kind", "source_id"),
        sa.CheckConstraint(
            "source_kind IN ('book', 'textbook')", name="ck_reading_positions_kind"
        ),
        sa.CheckConstraint("block_index >= 0", name="ck_reading_positions_index"),
    )
    op.create_index(
        "ix_reading_positions_student_updated",
        "reading_positions",
        ["student_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reading_positions_student_updated", table_name="reading_positions"
    )
    op.drop_table("reading_positions")

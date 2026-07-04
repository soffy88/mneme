"""add_timed_quiz

Revision ID: 75cc7c17edbe
Revises: 2b3c4d5e6f7a
Create Date: 2026-07-04 08:14:20.839083

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "75cc7c17edbe"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # T.8 周期限时小测：新表 + interactionsource 加 'quiz' 值。
    # 注：autogenerate 还检测出大量与本改动无关的既有模型/DB 漂移（已知问题，
    # 见 audit-fix/p2-14），本迁移只保留这两处，其余不动，不顺手修。
    op.create_table(
        "timed_quizzes",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "time_limit_seconds", sa.Integer(), server_default="300", nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # PG12+ 允许在事务内 ADD VALUE（同事务内不使用该值即可）
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'quiz'")


def downgrade() -> None:
    """Downgrade schema。PostgreSQL 不支持删 enum value，'quiz' 留存无害。"""
    op.drop_table("timed_quizzes")

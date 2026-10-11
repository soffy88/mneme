"""notebooks / notebook_records / cowriter_requests：学习者笔记本 + Co-Writer 限额账本

Revision ID: nbk1a2b3c4d5
Revises: bkc1a2b3c4d5
Create Date: 2026-10-11

DeepTutor Notebook / Co-Writer 对标（学习者自有、儿童安全）：
  - notebooks        : 学生自建的命名笔记本（owner-only）。
  - notebook_records : 笔记条目（source_type + source_id + kc_id + 内容）。
  - cowriter_requests: Co-Writer 每次调用的账本（只存字数/状态，不存原文），用于每日限额。
三表都带 student_id（未成年 PII 关联），同 PR 入 purge_service._STUDENT_TABLES。
笔记/写作永不进门控判据（无任何 mastery/gate 表引用）。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "nbk1a2b3c4d5"
down_revision = "bkc1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebooks",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint("student_id", "name", name="uq_notebooks_student_name"),
    )
    op.create_index("ix_notebooks_student_id", "notebooks", ["student_id"])

    op.create_table(
        "notebook_records",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "notebook_id",
            sa.String(50),
            sa.ForeignKey("notebooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("kc_id", sa.String(100), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('chat','book_block','solve','visualize','research',"
            "'cowriter','free_text')",
            name="ck_notebook_records_source_type",
        ),
    )
    op.create_index("ix_notebook_records_student_id", "notebook_records", ["student_id"])
    op.create_index(
        "ix_notebook_records_notebook_created", "notebook_records", ["notebook_id", "created_at"]
    )

    op.create_table(
        "cowriter_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_chars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index(
        "ix_cowriter_requests_student_created", "cowriter_requests", ["student_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_cowriter_requests_student_created", table_name="cowriter_requests")
    op.drop_table("cowriter_requests")
    op.drop_index("ix_notebook_records_notebook_created", table_name="notebook_records")
    op.drop_index("ix_notebook_records_student_id", table_name="notebook_records")
    op.drop_table("notebook_records")
    op.drop_index("ix_notebooks_student_id", table_name="notebooks")
    op.drop_table("notebooks")

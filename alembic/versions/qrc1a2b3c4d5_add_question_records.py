"""question_records（统一做题记录）+ wrong_questions 错题本复习列

Revision ID: qrc1a2b3c4d5
Revises: qbm1a2b3c4d5
Create Date: 2026-10-14

纯增量：新建 question_records 表；wrong_questions 只加可空列或带默认值的列，不改不删
既有列。question_records 每行属于一个学生（未成年 PII 关联）→ 已入
services/purge_service._STUDENT_TABLES（FC-2：新表同 PR 入清单）。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "qrc1a2b3c4d5"
down_revision = "qbm1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        # 不设 FK（同 question_bookmarks）：硬删走 purge_service._STUDENT_TABLES。
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(20), nullable=True),
        sa.Column("grade", sa.String(10), nullable=True),
        sa.Column("kc_ids", postgresql.JSONB(), nullable=True),
        sa.Column("question_ref", sa.String(128), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("image_key", sa.String(255), nullable=True),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("grader", sa.String(20), nullable=True),
        sa.Column("hints_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("understood", sa.Boolean(), nullable=True),
        sa.Column("wrong_question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_question_records_student_created", "question_records",
                    ["student_id", "created_at"])
    op.create_index("ix_question_records_student_source", "question_records",
                    ["student_id", "source"])

    op.add_column("wrong_questions", sa.Column("source", sa.String(32), nullable=True))
    op.add_column("wrong_questions", sa.Column("image_key", sa.String(255), nullable=True))
    op.add_column("wrong_questions",
                  sa.Column("question_record_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("wrong_questions", sa.Column("review_count", sa.Integer(),
                                               nullable=False, server_default=sa.text("0")))
    op.add_column("wrong_questions", sa.Column("review_correct_streak", sa.Integer(),
                                               nullable=False, server_default=sa.text("0")))
    op.add_column("wrong_questions",
                  sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wrong_questions",
                  sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_wrong_questions_student_due", "wrong_questions",
                    ["student_id", "fsrs_due"])


def downgrade() -> None:
    op.drop_index("ix_wrong_questions_student_due", table_name="wrong_questions")
    for col in ("graduated_at", "last_reviewed_at", "review_correct_streak",
                "review_count", "question_record_id", "image_key", "source"):
        op.drop_column("wrong_questions", col)
    op.drop_index("ix_question_records_student_source", table_name="question_records")
    op.drop_index("ix_question_records_student_created", table_name="question_records")
    op.drop_table("question_records")

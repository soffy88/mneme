"""question_bookmarks：学生收藏（☆）的题目（/v2/practice/bookmarks）

Revision ID: qbm1a2b3c4d5
Revises: kce1a2b3c4d5
Create Date: 2026-10-11

每条记录属于一个学生（student_id，未成年 PII 关联）→ 已入
services/purge_service._STUDENT_TABLES（FC-2：新表同 PR 入清单）。
source = posed（RequestQuestion 出的待答题，question_ref = q-…）| wrong（本人错题，
question_ref = wrong_questions.id）。prompt 是题干快照（服务端取，**绝不含参考答案**）。
收藏不进门控：不写证据、不改掌握度/FSRS。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "qbm1a2b3c4d5"
down_revision = "kce1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_bookmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("question_ref", sa.String(64), nullable=False),
        sa.Column("wrong_question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kc_id", sa.String(128), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("qtype", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("student_id", "source", "question_ref",
                            name="uq_question_bookmarks_student_ref"),
        sa.CheckConstraint("source IN ('posed', 'wrong')",
                           name="ck_question_bookmarks_source"),
    )
    op.create_index("ix_question_bookmarks_student_created", "question_bookmarks",
                    ["student_id", "created_at"])
    op.create_index("ix_question_bookmarks_student_kc", "question_bookmarks",
                    ["student_id", "kc_id"])


def downgrade() -> None:
    op.drop_index("ix_question_bookmarks_student_kc", table_name="question_bookmarks")
    op.drop_index("ix_question_bookmarks_student_created", table_name="question_bookmarks")
    op.drop_table("question_bookmarks")

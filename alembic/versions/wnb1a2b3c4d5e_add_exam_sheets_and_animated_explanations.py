"""组卷打印 + SVG 动画讲解：exam_sheets / exam_sheet_results /
animated_explanation_specs 三张表。

Revision ID: wnb1a2b3c4d5e
Revises: tfg1a2b3c4d5e
Create Date: 2026-11-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "wnb1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "all1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exam_sheets",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
    op.create_index(
        "ix_exam_sheets_student_id", "exam_sheets", ["student_id"]
    )
    op.create_table(
        "exam_sheet_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "sheet_id",
            sa.String(100),
            sa.ForeignKey("exam_sheets.id"),
            nullable=False,
        ),
        sa.Column("wrong_question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("sheet_id", "wrong_question_id"),
    )
    op.create_index(
        "ix_exam_sheet_results_sheet_id", "exam_sheet_results", ["sheet_id"]
    )
    op.create_table(
        "animated_explanation_specs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("question_id", sa.String(128), nullable=True),
        sa.Column("ku_id", sa.String(100), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
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
    op.create_index(
        "ix_animated_explanation_specs_ku_id",
        "animated_explanation_specs",
        ["ku_id"],
    )
    op.create_index(
        "ix_animated_explanation_specs_question_id",
        "animated_explanation_specs",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_animated_explanation_specs_question_id",
        table_name="animated_explanation_specs",
    )
    op.drop_index(
        "ix_animated_explanation_specs_ku_id",
        table_name="animated_explanation_specs",
    )
    op.drop_table("animated_explanation_specs")
    op.drop_index(
        "ix_exam_sheet_results_sheet_id", table_name="exam_sheet_results"
    )
    op.drop_table("exam_sheet_results")
    op.drop_index("ix_exam_sheets_student_id", table_name="exam_sheets")
    op.drop_table("exam_sheets")

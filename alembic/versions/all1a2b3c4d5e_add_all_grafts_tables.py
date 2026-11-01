"""add all-grafts tables

9 项全嫁接（DeepTutor 方法 4 项＋Parroto 方法 5 项，全部干净重写、
方法级嫁接）的持久化，ONE 个迁移：

- video_lesson_specs：视频课规格（ku 锚点可选）＋ verified 门禁位。
- dictation_specs / dictation_attempts：听写规格与只追加的尝试记录
  （成绩、错词、FSRS 排期快照；音频永不入库）。
- shadowing_specs / shadowing_attempts：跟读规格与只追加的尝试记录
  （评分、转写、弱项词；音频永不入库）。
- graded_audio_specs：分级有声规格。
- mock_exam_specs / mock_exam_attempts：模考规格与只追加的交卷记录。
- study_tasks：任务板任务（status/position/archived）。

i18n 为纯内存 catalog、citation_check 为无状态核查、retrieval_eval
为离线 harness：三者无持久化表。掌握裁决仍只认 BKT；verified 恒由
服务端门禁设置。

Revision ID: all1a2b3c4d5e
Revises: tfg1a2b3c4d5e
Create Date: 2026-11-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'all1a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'tfg1a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _spec_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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


def upgrade() -> None:
    op.create_table(
        "video_lesson_specs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("ku_id", sa.String(100), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
    op.create_index("ix_video_lesson_specs_ku_id", "video_lesson_specs", ["ku_id"])

    _spec_table("dictation_specs")
    op.create_table(
        "dictation_attempts",
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
        sa.Column("spec_id", sa.String(100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("missed_words", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("fsrs_card_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("fsrs_due", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_dictation_attempts_student_id", "dictation_attempts", ["student_id"])
    op.create_index("ix_dictation_attempts_spec_id", "dictation_attempts", ["spec_id"])

    _spec_table("shadowing_specs")
    op.create_table(
        "shadowing_attempts",
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
        sa.Column("spec_id", sa.String(100), nullable=False),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("transcript", sa.Text()),
        sa.Column("weak_words", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_shadowing_attempts_student_id", "shadowing_attempts", ["student_id"])
    op.create_index("ix_shadowing_attempts_spec_id", "shadowing_attempts", ["spec_id"])

    _spec_table("graded_audio_specs")
    _spec_table("mock_exam_specs")
    op.create_table(
        "mock_exam_attempts",
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
        sa.Column("spec_id", sa.String(100), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("late", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_mock_exam_attempts_student_id", "mock_exam_attempts", ["student_id"])
    op.create_index("ix_mock_exam_attempts_spec_id", "mock_exam_attempts", ["spec_id"])

    op.create_table(
        "study_tasks",
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
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.String(20), server_default=sa.text("'todo'"), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
    op.create_index("ix_study_tasks_student_id", "study_tasks", ["student_id"])
    op.create_index(
        "ix_study_tasks_student_due", "study_tasks", ["student_id", "due_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_study_tasks_student_due", table_name="study_tasks")
    op.drop_index("ix_study_tasks_student_id", table_name="study_tasks")
    op.drop_table("study_tasks")
    op.drop_index("ix_mock_exam_attempts_spec_id", table_name="mock_exam_attempts")
    op.drop_index("ix_mock_exam_attempts_student_id", table_name="mock_exam_attempts")
    op.drop_table("mock_exam_attempts")
    op.drop_table("mock_exam_specs")
    op.drop_table("graded_audio_specs")
    op.drop_index("ix_shadowing_attempts_spec_id", table_name="shadowing_attempts")
    op.drop_index("ix_shadowing_attempts_student_id", table_name="shadowing_attempts")
    op.drop_table("shadowing_attempts")
    op.drop_table("shadowing_specs")
    op.drop_index("ix_dictation_attempts_spec_id", table_name="dictation_attempts")
    op.drop_index("ix_dictation_attempts_student_id", table_name="dictation_attempts")
    op.drop_table("dictation_attempts")
    op.drop_table("dictation_specs")
    op.drop_index("ix_video_lesson_specs_ku_id", table_name="video_lesson_specs")
    op.drop_table("video_lesson_specs")

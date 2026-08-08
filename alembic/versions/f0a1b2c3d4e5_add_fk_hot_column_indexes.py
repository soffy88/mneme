"""add_fk_hot_column_indexes

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-08-01

C 审查项：FK 热点列补索引。live DB pg_indexes 实测（2026-08-01）——
多数学生子表的 student_id 及 join 列（paper_id/question_id/file_id/highlight_id）
无任何索引，purge 批量删除、家长-学生绑定反查、教材删除级联都是全表扫。

原则：只补「完全缺索引」的 FK 列（composite 已覆盖 leading 列的
kc_mastery/daily_missions/mastery_snapshots/cornell_progress 不重复建）。
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 纯学生子表 student_id（purge/统计热路径）
    op.create_index("ix_interaction_events_student_id", "interaction_events", ["student_id"])
    op.create_index("ix_guardian_consents_student_id", "guardian_consents", ["student_id"])
    op.create_index("ix_wrong_questions_student_id", "wrong_questions", ["student_id"])
    op.create_index("ix_wrong_questions_paper_id", "wrong_questions", ["paper_id"])
    op.create_index("ix_papers_student_id", "papers", ["student_id"])
    op.create_index("ix_socratic_sessions_student_id", "socratic_sessions", ["student_id"])
    op.create_index("ix_socratic_sessions_question_id", "socratic_sessions", ["question_id"])
    op.create_index("ix_lesson_pages_question_id", "lesson_pages", ["question_id"])
    op.create_index("ix_speaking_sessions_student_id", "speaking_sessions", ["student_id"])
    op.create_index("ix_timed_quizzes_student_id", "timed_quizzes", ["student_id"])
    op.create_index("ix_effortful_gains_student_id", "effortful_gains", ["student_id"])
    op.create_index("ix_streaks_student_id", "streaks", ["student_id"])
    op.create_index("ix_user_learner_profiles_student_id", "user_learner_profiles", ["student_id"])

    # 教材阅读器：highlight/note 的 join 列（级联删除与文件下架热路径）
    op.create_index("ix_highlights_file_id", "highlights", ["file_id"])
    op.create_index("ix_reading_notes_file_id", "reading_notes", ["file_id"])
    op.create_index("ix_reading_notes_highlight_id", "reading_notes", ["highlight_id"])

    # 家长绑定：parent_student 双列 join（pkey 是 parent_id 打头，student_id 单独要索引）
    op.create_index("ix_parent_student_student_id", "parent_student", ["student_id"])
    op.create_index("ix_parent_alerts_parent_id", "parent_alerts", ["parent_id"])
    op.create_index("ix_parent_alerts_student_id", "parent_alerts", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_parent_alerts_student_id", table_name="parent_alerts")
    op.drop_index("ix_parent_alerts_parent_id", table_name="parent_alerts")
    op.drop_index("ix_parent_student_student_id", table_name="parent_student")
    op.drop_index("ix_reading_notes_highlight_id", table_name="reading_notes")
    op.drop_index("ix_reading_notes_file_id", table_name="reading_notes")
    op.drop_index("ix_highlights_file_id", table_name="highlights")
    op.drop_index("ix_user_learner_profiles_student_id", table_name="user_learner_profiles")
    op.drop_index("ix_streaks_student_id", table_name="streaks")
    op.drop_index("ix_effortful_gains_student_id", table_name="effortful_gains")
    op.drop_index("ix_timed_quizzes_student_id", table_name="timed_quizzes")
    op.drop_index("ix_speaking_sessions_student_id", table_name="speaking_sessions")
    op.drop_index("ix_lesson_pages_question_id", table_name="lesson_pages")
    op.drop_index("ix_socratic_sessions_question_id", table_name="socratic_sessions")
    op.drop_index("ix_socratic_sessions_student_id", table_name="socratic_sessions")
    op.drop_index("ix_papers_student_id", table_name="papers")
    op.drop_index("ix_wrong_questions_paper_id", table_name="wrong_questions")
    op.drop_index("ix_wrong_questions_student_id", table_name="wrong_questions")
    op.drop_index("ix_guardian_consents_student_id", table_name="guardian_consents")
    op.drop_index("ix_interaction_events_student_id", table_name="interaction_events")

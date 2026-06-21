"""add_needs_image_and_normalize_wq_subject

wrong_questions 两项数据修复：
1. 公共题库(student_id IS NULL) subject 中文→英文（数学→math 等）
2. 新增 needs_image boolean 字段，标记含 <ImageHere> 占位的题目

Revision ID: 51e587e6c96c
Revises: 296800f14b43
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '51e587e6c96c'
down_revision: Union[str, Sequence[str], None] = '296800f14b43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SUBJECT_MAP = [
    ('数学', 'math'),
    ('物理', 'physics'),
    ('英语', 'english'),
    ('语文', 'chinese'),
]


def upgrade() -> None:
    # 1. 添加 needs_image 字段
    op.add_column(
        'wrong_questions',
        sa.Column('needs_image', sa.Boolean(), nullable=False, server_default='false'),
    )

    # 2. 公共题库 subject 中文→英文（只改 student_id IS NULL 的，不动学生个人错题）
    for cn, en in _SUBJECT_MAP:
        op.execute(
            f"UPDATE wrong_questions SET subject = '{en}' "
            f"WHERE subject = '{cn}' AND student_id IS NULL"
        )

    # 3. 标记含 <ImageHere> 的题目
    op.execute(
        "UPDATE wrong_questions SET needs_image = true "
        "WHERE question_text LIKE '%<ImageHere>%'"
    )


def downgrade() -> None:
    op.drop_column('wrong_questions', 'needs_image')
    for cn, en in _SUBJECT_MAP:
        op.execute(
            f"UPDATE wrong_questions SET subject = '{cn}' "
            f"WHERE subject = '{en}' AND student_id IS NULL"
        )

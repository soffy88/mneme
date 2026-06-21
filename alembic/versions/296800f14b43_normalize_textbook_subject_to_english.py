"""normalize_textbook_subject_to_english

将 textbooks.subject 中的中文学科名统一为英文：
数学→math, 物理→physics, 英语→english, 语文→chinese

Revision ID: 296800f14b43
Revises: 54bdd75b827d
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = '296800f14b43'
down_revision: Union[str, Sequence[str], None] = '54bdd75b827d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MAPPING = [
    ('数学', 'math'),
    ('物理', 'physics'),
    ('英语', 'english'),
    ('语文', 'chinese'),
]


def upgrade() -> None:
    for cn, en in _MAPPING:
        op.execute(f"UPDATE textbooks SET subject = '{en}' WHERE subject = '{cn}'")


def downgrade() -> None:
    for cn, en in _MAPPING:
        op.execute(f"UPDATE textbooks SET subject = '{cn}' WHERE subject = '{en}'")

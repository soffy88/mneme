"""add phonetic_arpabet to vocabulary_items (CMUdict 原始音标)

Revision ID: a7b8c9d0e1f2
Revises: b7c8d9e0f1a2
Create Date: 2026-10-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 phonetic_arpabet，存 CMUdict 原始 ARPAbet。

    为什么不复用 phonetic_us：那一列由教材词表填 **IPA**（/ˈæpl/），而 CMUdict 给
    的是 **ARPAbet**（AE1 P AH0 L）。混写会让同一列出现两套记音体系。单独一列
    存权威原始值，未来的 IPA 转换或 TTS 都从它派生——原始数据永远比转换结果
    可信，映射错一个音素就是给孩子看错的发音。

    phonetic_uk / phonetic_generic 保持 NULL：CMUdict 只有北美发音，编造英音
    是错的，宁可留空等真实英音源。

    合规：这是 vocabulary_items（全局共享参考数据，非学生 PII）加一列，不是新表，
    故不涉及 purge_service._STUDENT_TABLES（该表也不应包含 vocabulary_items）。
    """
    op.add_column("vocabulary_items", sa.Column("phonetic_arpabet", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("vocabulary_items", "phonetic_arpabet")
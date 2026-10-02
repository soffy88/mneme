"""add vocabulary_collocations（课标用法搭配表）

Revision ID: c8d9e0f1a2b3
Revises: f2a3b4c5d6e7
Create Date: 2026-10-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """课标「用法搭配」：短语搭配是**独立表**而不是 vocabulary_items 的列。

    理由同 vocabulary_affixes：搭配是可反查的结构化数据 —— 「哪些词共享
    `take care of`」「`out of breath` 属于哪一类」是真实需求，独立表才建得起
    索引；堆进 JSONB/数组列就只能整串匹配。

    词义不动：本表的搭配来自《2022版课标新增词汇》OCR，而 vocabulary_items.
    meaning_cn 来自**教材词表原文**（更完整）。课标给的是「适合该学段的精简
    义项」（实测 accident 课标=交通事故;意外遭遇，教材=事故；意外；意外事件；
    机遇），两者粒度不同而非冲突，**不覆盖** meaning_cn。

    数据源是扫描件 OCR，故保留 source + confidence 以便追溯与抽检。
    合规：全局参考数据非学生 PII（同 vocabulary_items）；FK ON DELETE CASCADE。
    """
    op.create_table(
        "vocabulary_collocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("vocabulary_item_id", sa.String(100), nullable=False),
        sa.Column("phrase_en", sa.Text(), nullable=False),
        sa.Column("phrase_cn", sa.Text(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False,
                  server_default=sa.text("'CURRICULUM_OCR'")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_collocations"),
        sa.ForeignKeyConstraint(
            ["vocabulary_item_id"],
            ["vocabulary_items.id"],
            name="fk_vocab_collocations_vocabulary_item_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("vocabulary_item_id", "phrase_en", "phrase_cn",
                            name="uq_vocab_collocation"),
    )
    # 反查"哪些词共享同一个搭配" / "一个词的全部搭配"
    op.create_index("ix_vocab_collocation_phrase_en", "vocabulary_collocations", ["phrase_en"])
    op.create_index("ix_vocab_collocation_item", "vocabulary_collocations",
                    ["vocabulary_item_id"])


def downgrade() -> None:
    op.drop_index("ix_vocab_collocation_item", table_name="vocabulary_collocations")
    op.drop_index("ix_vocab_collocation_phrase_en", table_name="vocabulary_collocations")
    op.drop_table("vocabulary_collocations")
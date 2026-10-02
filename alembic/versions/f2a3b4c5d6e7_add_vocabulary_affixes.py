"""add vocabulary_affixes（词根词缀分解表）

Revision ID: f2a3b4c5d6e7
Revises: a7b8c9d0e1f2
Create Date: 2026-10-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """词根词缀分解：prefix · root · suffix 三个独立列，展示时才用 · 连起来。

    为什么不把 "pre·dict" 这种拼好的串直接存一列：词根词缀是**可查询的**结构化
    数据（"所有用 -able 的词"是真实需求：同根派生词横向串联、词族记忆）。
    存成拼接串就只能整串匹配，无法索引。展示格式由
    services.vocab_affixes.format_affix_chain() 负责，不落库。

    为什么独立成表而不加在 vocabulary_items 上：词根词缀是**另一张词表**的内容
    （同一词根横跨几十个互不相干的单词），塞进 vocabulary_items 会让「按词根
    反查」变成全表扫描；独立表建索引成本低。

    每个词一条（vocabulary_item_id UNIQUE）：只存首选分解，避免渲染歧义。

    合规：全局参考数据，非学生 PII（同 vocabulary_items，不进 purge 清单）；
    FK 带 ON DELETE CASCADE，将来 vocabulary_items 若纳入硬删除，本表自动随之。
    """
    op.create_table(
        "vocabulary_affixes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        # vocabulary_items.id 是 varchar(100)（不是 uuid）——早期英语词表用
        # uuid5(normalized_form) 或 'vocab-<word>' 当主键，故跟随其类型。
        sa.Column("vocabulary_item_id", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(32), nullable=True),
        sa.Column("root", sa.String(48), nullable=False),
        sa.Column("suffix", sa.String(32), nullable=True),
        sa.Column("meaning_cn", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(120), nullable=True),
        sa.Column("source", sa.String(32), nullable=False,
                  server_default=sa.text("'WLLM'")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_affixes"),
        sa.ForeignKeyConstraint(
            ["vocabulary_item_id"],
            ["vocabulary_items.id"],
            name="fk_vocabulary_affixes_vocabulary_item_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("vocabulary_item_id", name="uq_vocab_affix_item"),
    )
    # 按词根反查同根词是这张表的主要用途，必须有索引
    op.create_index("ix_vocab_affix_root", "vocabulary_affixes", ["root"])
    op.create_index("ix_vocab_affix_suffix", "vocabulary_affixes", ["suffix"])


def downgrade() -> None:
    op.drop_index("ix_vocab_affix_suffix", table_name="vocabulary_affixes")
    op.drop_index("ix_vocab_affix_root", table_name="vocabulary_affixes")
    op.drop_table("vocabulary_affixes")
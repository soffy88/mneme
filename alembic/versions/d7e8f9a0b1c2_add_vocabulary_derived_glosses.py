"""add vocabulary_derived_glosses（从真实语料派生的中文释义）

Revision ID: d7e8f9a0b1c2
Revises: e6f7a8b9c0d2
Create Date: 2026-10-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为「有真实语境句、但没有中文释义」的词补一份派生释义。

    ## 为什么不写进 `vocabulary_items.meaning_cn`

    `meaning_cn` 是「教材词表原文」的载体 —— 它承载**可追溯性**：学生看到的释义
    能指回教材。实测有 **461** 个核心单词（有 NCE 真实句）压根没有中文释义，
    其中 **459** 个的 `canonical_meaning` 装的是**纯音标**（`[ˈdaɪət]`、
    `[ɪˈlektrɪk]`、`[kəˈmɪtmənt]`），确定性派生路径完全走不通
    （`derive_meaning_from_canonical` 实测可派生 = 0）。

    把 LLM 生成的释义直接写进那一列，会**一次性丢掉出处信息**：之后无法区分
    「教材原文」与「模型从语料句推的」。这正是本仓在词根那侧已经踩过并解决过的
    问题 —— `vocabulary_affixes` 专门加了 `etymology_status` 三档，而不是把
    「记忆联想」塞进释义字段。

    所以本表**独立存**，出处写在 `source_kind` 里，读取方
    （`services/vocab_meaning.py`）按档位返回 `derived_from_corpus`，
    展示层可以据此标注「据真实例句派生」。

    ## 为什么这批数据可信度高于「凭空生成」

    释义由既有 `oprim._vocab_gloss_generate` 生成，而它**只读**调用方从
    `timed_sentences` 确定性抽取的真实句子 —— 例句不是模型编的。
    `source_sentence_id` 把「用了哪一句」记下来，可回溯。

    合规：全局参考数据，非学生 PII（同 `vocabulary_items`），FK CASCADE，不进 purge 清单。
    """
    op.create_table(
        "vocabulary_derived_glosses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("vocabulary_item_id", sa.String(100), nullable=False),
        sa.Column("gloss", sa.Text(), nullable=False),
        # 一词一条：避免渲染时出现「两个释义挑哪个」的歧义
        sa.Column("source_kind", sa.String(24), nullable=False,
                  server_default=sa.text("'corpus_llm'")),
        # 「用了哪一句」——释义的可回溯依据；句在 timed_sentences，这里只存 id
        sa.Column("source_sentence_id", sa.String(100), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_derived_glosses"),
        sa.ForeignKeyConstraint(
            ["vocabulary_item_id"],
            ["vocabulary_items.id"],
            name="fk_vocab_derived_glosses_vocabulary_item_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("vocabulary_item_id",
                            name="uq_vocab_derived_gloss_item"),
        sa.CheckConstraint(
            "source_kind = 'corpus_llm'",
            name="ck_vocab_derived_gloss_source_kind",
        ),
    )
    op.create_index("ix_vocab_derived_gloss_item", "vocabulary_derived_glosses",
                    ["vocabulary_item_id"])


def downgrade() -> None:
    op.drop_index("ix_vocab_derived_gloss_item",
                  table_name="vocabulary_derived_glosses")
    op.drop_table("vocabulary_derived_glosses")
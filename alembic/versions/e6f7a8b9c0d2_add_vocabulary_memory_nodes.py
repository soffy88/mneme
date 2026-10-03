"""add vocabulary_memory_nodes（词汇记忆节点表）

Revision ID: e6f7a8b9c0d2
Revises: a3b4c5d6e7f8
Create Date: 2026-10-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f7a8b9c0d2"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """词汇记忆节点：LLM 生成的**联想层**，按词一条。

    本表**只**存生成内容。事实层仍在各自既有表里，不复制（单源红线，见
    MNEME_CORE3000_MEMORY_ENGINE_P0_SPEC.md §4）：

        vocabulary_items        词 / 词性 / 释义 / 音标 / 例句
        vocabulary_affixes      前缀·词根·后缀 + etymology_status（分档）
        vocabulary_collocations 课标搭配
        vocabulary_xiangxing    象形 9000

    故本表**刻意没有** etymology / root_logic / collocations 列：那些是事实，
    复制进来就多一份会漂移的第二来源，而 vocabulary_affixes 的 379 条已经带
    reference_confirmed / mnemonic_association / disputed 三档可信度——一个扁平
    字符串会把「可当词源讲」和「只是记忆联想」抹平。渲染时读原表即可。

    同样**没有** media_reference（影视片段）：2026-10-02 已因未成年 + 版权
    否决，不建列以免复活。也没有 image_url —— 外部图片 provider 集成数为 0，
    存一个恒为 NULL 的 URL 列等于给「图片覆盖率 0%」这个事实做假。

    context_tier 落库的是**实际取到的层**（1..5），不是最高可用层；tier=5
    （无语境）时 context_absence_reason 必填。上下文证据存 sentence_id 而非
    复制句子文本，句子本身在 timed_sentences，改了这里不会读到旧句。
    """
    op.create_table(
        "vocabulary_memory_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("vocabulary_item_id", sa.String(100), nullable=False),
        sa.Column("tier", sa.String(1), nullable=False),
        sa.Column("core_image", sa.Text(), nullable=False),
        sa.Column("semantic_core", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scene", sa.Text(), nullable=True),
        sa.Column("family_network", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("sound_hook", sa.Text(), nullable=True),
        sa.Column("spelling_hook", sa.Text(), nullable=True),
        sa.Column("recall_question", sa.Text(), nullable=False),
        sa.Column("answer", sa.String(100), nullable=False),
        sa.Column("image_prompt", sa.Text(), nullable=True),
        sa.Column("animation_candidate", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("animation_scene", sa.Text(), nullable=True),
        sa.Column("context_tier", sa.Integer(), nullable=False),
        sa.Column("context_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("context_absence_reason", sa.Text(), nullable=True),
        sa.Column("generation_model", sa.String(64), nullable=True),
        sa.Column("generation_version", sa.String(16), nullable=False,
                  server_default=sa.text("'p0'")),
        sa.Column("quality_score", sa.Float(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("verified", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_memory_nodes"),
        sa.ForeignKeyConstraint(
            ["vocabulary_item_id"],
            ["vocabulary_items.id"],
            name="fk_vocab_memory_nodes_vocabulary_item_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("vocabulary_item_id", name="uq_vocab_memory_node_item"),
        sa.CheckConstraint("context_tier >= 1 AND context_tier <= 5",
                           name="ck_vocab_memory_node_context_tier"),
        sa.CheckConstraint("quality_score >= 0 AND quality_score <= 1",
                           name="ck_vocab_memory_node_quality_score"),
        # tier=5（无真实语境）必须写明为什么，否则「没有语境」和「我们没接入教材」
        # 无法区分 —— 教材优先是产品承诺，静默降级会让它消失。
        sa.CheckConstraint(
            "context_tier < 5 OR context_absence_reason IS NOT NULL",
            name="ck_vocab_memory_node_absence_reason",
        ),
    )
    op.create_index("ix_vocab_memory_node_item", "vocabulary_memory_nodes",
                    ["vocabulary_item_id"])
    op.create_index("ix_vocab_memory_node_tier", "vocabulary_memory_nodes", ["tier"])
    # 未通过质量门的节点也要能被查出来做人工复核/重跑，不能只索引 verified=true。
    op.create_index("ix_vocab_memory_node_unverified", "vocabulary_memory_nodes",
                    ["verified"])


def downgrade() -> None:
    op.drop_index("ix_vocab_memory_node_unverified", table_name="vocabulary_memory_nodes")
    op.drop_index("ix_vocab_memory_node_tier", table_name="vocabulary_memory_nodes")
    op.drop_index("ix_vocab_memory_node_item", table_name="vocabulary_memory_nodes")
    op.drop_table("vocabulary_memory_nodes")
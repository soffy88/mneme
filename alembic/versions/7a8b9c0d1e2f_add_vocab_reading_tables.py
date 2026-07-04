"""add_vocab_reading_tables

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-07-04

U.19 英语习得型范式：词汇 FSRS（vocabulary_items）+ 分级泛读（reading_passages），
数据自 Simple English Wikipedia（CC BY-SA 4.0）自建语料库统计得出，见
services/models.py 顶部说明。词汇复现调度复用既有 kc_mastery（InteractionSource
新增 vocab_review 枚举值），本迁移只建内容表 + 枚举值，不新建调度表。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, Sequence[str], None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'vocab_review'")

    op.create_table(
        "vocabulary_items",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("word", sa.String(length=100), nullable=False),
        sa.Column("pos", sa.String(length=20), nullable=True),
        sa.Column("meaning_cn", sa.Text(), nullable=True),
        sa.Column("example_sentence", sa.Text(), nullable=True),
        sa.Column("frequency_rank", sa.Integer(), nullable=False),
        sa.Column("frequency_band", sa.Integer(), nullable=False),
        sa.Column(
            "source", sa.String(length=50), server_default=sa.text("'simplewiki'")
        ),
        sa.Column("ai_generated", sa.Boolean(), server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_vocabulary_items_frequency_band", "vocabulary_items", ["frequency_band"]
    )

    op.create_table(
        "reading_passages",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("subject", sa.String(length=20), server_default=sa.text("'english'")),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column(
            "license", sa.String(length=50), server_default=sa.text("'CC BY-SA 4.0'")
        ),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("readability_score", sa.Float(), nullable=False),
        sa.Column("difficulty_band", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_reading_passages_difficulty_band", "reading_passages", ["difficulty_band"]
    )


def downgrade() -> None:
    op.drop_index("ix_reading_passages_difficulty_band", table_name="reading_passages")
    op.drop_table("reading_passages")
    op.drop_index("ix_vocabulary_items_frequency_band", table_name="vocabulary_items")
    op.drop_table("vocabulary_items")
    # Postgres 不能移除 enum 值，vocab_review 保留

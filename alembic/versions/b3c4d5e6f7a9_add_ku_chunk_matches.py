"""add ku_chunk_matches (W3 A3 KU<->chunk inferred linkage)

Revision ID: b3c4d5e6f7a9
Revises: a2b3c4d5e6f7
Create Date: 2026-07-18

ku_chunk_matches：KU 与教材 chunk 的推断挂接（embedding 检索匹配，概率性，非权威）。
KU 本身无原生出处（LLM 抽取，provenance 列一直是空的），这张表补的是"推断出处"，
与 knowledge_units.provenance（KU 抽取管道自己的来源字段，语义不同）分开存，
不覆盖/不混用既有字段——避免两种"出处"概念混在一列里。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "b3c4d5e6f7a9"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ku_chunk_matches",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "ku_id",
            sa.String(100),
            sa.ForeignKey("knowledge_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(50),
            sa.ForeignKey("textbook_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer, nullable=False),  # 1=最佳匹配，2/3=候选
        sa.Column("score", sa.Float, nullable=False),  # cosine 相似度 [0,1]
        sa.Column(
            "method", sa.String(50), nullable=False
        ),  # 如 embedding_cosine_qwen3-embedding
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_kcm_ku_id", "ku_chunk_matches", ["ku_id"])
    op.create_index(
        "ix_kcm_ku_rank", "ku_chunk_matches", ["ku_id", "rank"], unique=True
    )


def downgrade() -> None:
    op.drop_table("ku_chunk_matches")

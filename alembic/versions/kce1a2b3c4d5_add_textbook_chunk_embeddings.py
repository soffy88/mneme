"""textbook_chunk_embeddings：按模型分存的 chunk 向量（CPU embedding 侧车）

Revision ID: kce1a2b3c4d5
Revises: rsr1a2b3c4d5
Create Date: 2026-10-11

RTX 3080 掉卡后旧的 4096 维 qwen3-embedding（textbook_chunks.embedding）无法再
为新 query 产生同空间向量。新向量（CPU 侧车模型，默认 bge-small-zh-v1.5 512 维）存新表，主键 (chunk_id, model)，
旧列原样保留不动（未经验证前不删旧数据；回退 MNEME_EMBED_BACKEND=legacy 即可）。
chunk 删除时级联删除。纯教材内容，无学生 PII，不进 purge 清单。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "kce1a2b3c4d5"
down_revision = "rsr1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "textbook_chunk_embeddings",
        sa.Column(
            "chunk_id",
            sa.String(50),
            sa.ForeignKey("textbook_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tce_model", "textbook_chunk_embeddings", ["model"])


def downgrade() -> None:
    op.drop_index("ix_tce_model", table_name="textbook_chunk_embeddings")
    op.drop_table("textbook_chunk_embeddings")

"""add verified fields to ku_chunk_matches (W3 pre-Part-B human review gate)

Revision ID: c4d5e6f7a8ba
Revises: b3c4d5e6f7a9
Create Date: 2026-07-19

Book Engine 引用教材原文前，KU<->chunk 挂接需人工确认（A3 精度天花板：~85%命中率，
1/20 词汇碰撞误判——embedding 分数分不出"对的0.78"和"碰撞的0.78"，靠人工过一遍）。
verified=false 是默认/未审状态；Book Engine 的引用查询只认 verified=true 的行。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "c4d5e6f7a8ba"
down_revision = "b3c4d5e6f7a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ku_chunk_matches",
        sa.Column(
            "verified", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "ku_chunk_matches",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ku_chunk_matches", sa.Column("verified_note", sa.Text, nullable=True)
    )
    op.create_index(
        "ix_kcm_ku_verified",
        "ku_chunk_matches",
        ["ku_id", "verified"],
        postgresql_where=sa.text("verified = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_kcm_ku_verified", table_name="ku_chunk_matches")
    op.drop_column("ku_chunk_matches", "verified_note")
    op.drop_column("ku_chunk_matches", "verified_at")
    op.drop_column("ku_chunk_matches", "verified")

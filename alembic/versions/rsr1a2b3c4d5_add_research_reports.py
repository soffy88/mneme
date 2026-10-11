"""research_reports：研究报告（/v1/research，DeepTutor Deep Research 儿童安全版）

Revision ID: rsr1a2b3c4d5
Revises: rdp1a2b3c4d5
Create Date: 2026-10-11

每条记录属于一个学生（student_id，未成年 PII 关联）→ 已入
services/purge_service._STUDENT_TABLES（FC-2：新表同 PR 入清单）。
report/sources 是 JSON：报告结构 + 本次检索到的教材切片（书/页/chunk_id/摘录）。
研究记录不进门控：不写证据、不改掌握度。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "rsr1a2b3c4d5"
down_revision = "rdp1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_reports",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("grade", sa.String(10), nullable=True),
        sa.Column("persona_slug", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_research_reports_student_created", "research_reports",
                    ["student_id", "created_at"])
    op.create_index("ix_research_reports_created", "research_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_research_reports_created", table_name="research_reports")
    op.drop_index("ix_research_reports_student_created", table_name="research_reports")
    op.drop_table("research_reports")

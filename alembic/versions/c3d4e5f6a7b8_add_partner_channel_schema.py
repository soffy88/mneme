"""add partner channel schema (W5 Part A4)

Revision ID: c3d4e5f6a7b8
Revises: d5e6f7a8b9c1
Create Date: 2026-07-19

W5 Partners 数据隔离（FC-2）。纯新增两张表，落已有 `agent` schema（同一 Postgres
实例，对照既有 gate/agent schema 先例，无 FK、可任意序删）：

  - agent.partner_channel_bindings : 学生 <-> 渠道(WeCom/Feishu 等) 推送目标绑定
    （群 webhook URL）。W5 v1 push-only，零真实学习者，本表上线时预期为空——
    绑定关系由后续 MCP 工具写入，本 migration 只建表。
  - agent.partner_push_log         : 每次真实推送的流水（供 oskill/partner_dispatch
    做节流/去重，同 DeepTutor AlerterEngine 的 throttle_seconds/dedup_bucket_seconds
    语义，此处直接查表实现，非引入 oservi 依赖）。

两表均带 student_id（未成年 PII 关联），FC-2：同 PR 已把两表加入
services/purge_service._STUDENT_TABLES。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "c3d4e5f6a7b8"
down_revision = "d5e6f7a8b9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent schema 已由 e6f7a8b9c0d1 建过，这里幂等保护（CREATE SCHEMA IF NOT EXISTS）。
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")

    # agent.partner_channel_bindings —— 学生绑定的推送目标（渠道 + 群 webhook）
    op.create_table(
        "partner_channel_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),  # "wecom" | "feishu"
        sa.Column("target", sa.Text, nullable=False),  # 群 webhook URL（含 key）
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "student_id", "channel", name="uq_agent_partner_binding_student_channel"
        ),
        schema="agent",
    )
    op.create_index(
        "ix_agent_partner_binding_student",
        "partner_channel_bindings",
        ["student_id"],
        schema="agent",
    )

    # agent.partner_push_log —— 推送流水（节流/去重 + 可审计溯源）
    op.create_table(
        "partner_push_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),  # 如 "review_due"
        sa.Column("dedup_key", sa.String(100), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="agent",
    )
    op.create_index(
        "ix_agent_partner_push_log_student",
        "partner_push_log",
        ["student_id"],
        schema="agent",
    )
    op.create_index(
        "ix_agent_partner_push_log_dedup",
        "partner_push_log",
        ["student_id", "channel", "dedup_key"],
        schema="agent",
    )


def downgrade() -> None:
    op.drop_index("ix_agent_partner_push_log_dedup", "partner_push_log", schema="agent")
    op.drop_index(
        "ix_agent_partner_push_log_student", "partner_push_log", schema="agent"
    )
    op.drop_table("partner_push_log", schema="agent")
    op.drop_index(
        "ix_agent_partner_binding_student", "partner_channel_bindings", schema="agent"
    )
    op.drop_table("partner_channel_bindings", schema="agent")

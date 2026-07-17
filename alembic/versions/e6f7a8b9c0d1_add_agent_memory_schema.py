"""add agent memory schema (S3 三层 Memory)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-17

三层 Agent Memory 骨架（见 MNEME_MASTER_DESIGN.md 附录·Agent 三层 Memory）。纯新增独立
schema `agent`，不动 mneme 既有表。同一 Postgres 实例（对照既有 `gate` schema 先例），
agent 进程本身仍零 DB 连接（FC-5）——全程经 services/memory 读写。

  - agent.working_memory  : 会话内短期上下文，expires_at TTL。
  - agent.episodic_memory : 逐次交互流水，只增不改。
  - agent.semantic_memory : 按 (student_id, topic) 唯一的沉淀摘要，merge/update 覆盖式演进。

三表均带真实 student_id（未成年 PII 关联），FC-2：同 PR 已把三表加入
services/purge_service._STUDENT_TABLES。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")

    # agent.working_memory —— 会话内短期上下文，TTL 过期视为不可读
    op.create_table(
        "working_memory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="agent",
    )
    op.create_index(
        "ix_agent_working_student", "working_memory", ["student_id"], schema="agent"
    )

    # agent.episodic_memory —— 逐次交互流水，只增不改（对齐 append_episode.py 语义）
    op.create_table(
        "episodic_memory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(50), nullable=False),  # 事件类型，如 "tutor_turn"
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=True),  # 可追溯来源，非必填
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="agent",
    )
    op.create_index(
        "ix_agent_episodic_student", "episodic_memory", ["student_id"], schema="agent"
    )

    # agent.semantic_memory —— 沉淀摘要，(student_id, topic) 唯一
    op.create_table(
        "semantic_memory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column(
            "merged_from", postgresql.JSONB, nullable=True
        ),  # 溯源 episodic id 列表
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "student_id", "topic", name="uq_agent_semantic_student_topic"
        ),
        schema="agent",
    )
    op.create_index(
        "ix_agent_semantic_student", "semantic_memory", ["student_id"], schema="agent"
    )


def downgrade() -> None:
    op.drop_index("ix_agent_semantic_student", "semantic_memory", schema="agent")
    op.drop_table("semantic_memory", schema="agent")
    op.drop_index("ix_agent_episodic_student", "episodic_memory", schema="agent")
    op.drop_table("episodic_memory", schema="agent")
    op.drop_index("ix_agent_working_student", "working_memory", schema="agent")
    op.drop_table("working_memory", schema="agent")
    op.execute("DROP SCHEMA IF EXISTS agent")

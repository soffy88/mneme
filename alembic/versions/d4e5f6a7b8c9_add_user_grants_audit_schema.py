"""add user grants + audit log schema (W5 Part B)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-19

W5 多用户：admin 授权 + 审计日志。纯新增两张表，落已有 `agent` schema（同一
Postgres 实例，无 FK，可任意序删）。admin 身份不建表——`ADMIN_USER_IDS` 环境变量
白名单（用户拍板：不碰 User/UserRole，零改动既有账号体系）。

  - agent.user_grants : 按学生 admin-curated 的工具/模型授权，deny-by-default
    （enabled_tools/allowed_models 为 NULL = 拒绝一切，非"默认放行"）。
  - agent.audit_log    : 用户操作审计（append-only）。

两表均带 student_id（未成年 PII 关联——即便是被判定为 admin 的账号，本质上仍是
users 表里的同一个 User 行），FC-2：同 PR 已把两表加入
services/purge_service._STUDENT_TABLES。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")

    # agent.user_grants —— 每学生一行，deny-by-default
    op.create_table(
        "user_grants",
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        # NULL = 拒绝一切（deny-by-default）；JSON 数组 = 白名单。
        sa.Column("enabled_tools", postgresql.JSONB, nullable=True),
        sa.Column("allowed_models", postgresql.JSONB, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by", postgresql.UUID(as_uuid=True), nullable=True
        ),  # 操作的 admin User.id
        schema="agent",
    )

    # agent.audit_log —— 用户操作审计，只增不改
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="agent",
    )
    op.create_index(
        "ix_agent_audit_log_student", "audit_log", ["student_id"], schema="agent"
    )


def downgrade() -> None:
    op.drop_index("ix_agent_audit_log_student", "audit_log", schema="agent")
    op.drop_table("audit_log", schema="agent")
    op.drop_table("user_grants", schema="agent")

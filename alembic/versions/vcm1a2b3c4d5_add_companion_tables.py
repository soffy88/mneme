"""companion_settings / companion_usage / companion_messages：语音辅导 + AI 陪学陪练

Revision ID: vcm1a2b3c4d5
Revises: vlc1a2b3c4d5
Create Date: 2026-10-22

三张表都按 student_id 关联未成年人 → 已入 services/purge_service._STUDENT_TABLES（FC-2）。
日志内容在写入前已 PII 打码（services.companion_safety.redact_pii）。不进门控、不写掌握度。
"""

from alembic import op
import sqlalchemy as sa

revision = "vcm1a2b3c4d5"
down_revision = "vlc1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companion_settings",
        sa.Column("student_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(16), nullable=False, server_default="小智"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("daily_cap_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("session_limit_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "companion_usage",
        sa.Column("student_id", sa.String(36), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "companion_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("flags", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_companion_messages_student_created", "companion_messages", ["student_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_companion_messages_student_created", table_name="companion_messages")
    op.drop_table("companion_messages")
    op.drop_table("companion_usage")
    op.drop_table("companion_settings")

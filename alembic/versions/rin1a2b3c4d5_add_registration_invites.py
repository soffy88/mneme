"""registration_invites：邀请制学生注册码

Revision ID: rin1a2b3c4d5
Revises: vcm1a2b3c4d5
Create Date: 2026-10-22

上线改为邀请制：管理员生成单次使用的邀请码，学生凭码注册，不依赖 SMTP/SMS。
邀请码是准入控制的唯一凭据；兑换后记录 student_id/used_at，便于审计与追责。

兑换记录含未成年人 student_id → 同 PR 入 services/purge_service._STUDENT_TABLES。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "rin1a2b3c4d5"
down_revision = "vcm1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_invites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(24), nullable=False, unique=True),
        sa.Column("note", sa.String(120), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_registration_invites_created_at",
        "registration_invites",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_registration_invites_created_at", table_name="registration_invites"
    )
    op.drop_table("registration_invites")

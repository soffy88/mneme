"""add evaluation ModelRegistry

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-25

Model metadata is not student-scoped.  The registry makes train/eval windows,
code identity, status and rollback metadata auditable without storing a second
copy of learning events.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("model_type", sa.String(length=80), nullable=False),
        sa.Column("code_sha", sa.String(length=128), nullable=False),
        sa.Column("train_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="shadow",
            nullable=False,
        ),
        sa.Column("rollback_to", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('shadow', 'candidate', 'production', 'retired')",
            name="ck_model_registry_status",
        ),
        sa.CheckConstraint(
            "train_end <= eval_start AND eval_start < eval_end",
            name="ck_model_registry_time_windows",
        ),
        sa.PrimaryKeyConstraint("model_id"),
    )
    op.create_index(
        "ix_model_registry_type_status",
        "model_registry",
        ["model_type", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_registry_type_status", table_name="model_registry")
    op.drop_table("model_registry")

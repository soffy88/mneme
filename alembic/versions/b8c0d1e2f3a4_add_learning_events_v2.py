"""add append-only Learning Event v2 fact table

Revision ID: b8c0d1e2f3a4
Revises: 8ad19eb4ab90
Create Date: 2026-08-24

The table is deliberately separate from interaction_events. Existing BKT/FSRS
write paths remain the operational projection path, while the rollout flag
dual-writes the same immutable fact for replay and interoperability consumers.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "8ad19eb4ab90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), server_default="2", nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=200), nullable=False),
        sa.Column("content_version", sa.String(length=100), nullable=True),
        sa.Column(
            "knowledge_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "item_features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "process_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metacognitive",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "intervention", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("privacy_class", sa.String(length=2), server_default="P1", nullable=False),
        sa.Column("trace_id", sa.String(length=200), nullable=True),
        sa.Column("supersedes_event_id", sa.UUID(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("event_checksum", sa.String(length=64), nullable=False),
        sa.CheckConstraint("schema_version = '2'", name="ck_learning_events_v2"),
        sa.CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_learning_events_privacy_class",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("event_id", name="uq_learning_events_event_id"),
    )
    op.create_index(
        "ix_learning_events_student_occurred",
        "learning_events",
        ["student_id", "occurred_at", "received_at", "event_id"],
    )
    op.create_index(
        "ix_learning_events_student_received",
        "learning_events",
        ["student_id", "received_at", "event_id"],
    )
    op.create_index(
        "ix_learning_events_supersedes_event_id",
        "learning_events",
        ["supersedes_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_learning_events_supersedes_event_id", table_name="learning_events")
    op.drop_index("ix_learning_events_student_received", table_name="learning_events")
    op.drop_index("ix_learning_events_student_occurred", table_name="learning_events")
    op.drop_table("learning_events")

"""add evidence-grounded memory graph tables

Revision ID: c1d2e3f4a5b6
Revises: b8c0d1e2f3a4
Create Date: 2026-08-24

The graph stores explanatory claims and their source evidence separately from
the append-only learning event log.  It is a projection/read model and never
stores mastery as an authority.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b8c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "memory_claims",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("claim_type", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("privacy_class", sa.String(length=2), server_default="P1", nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_default(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_memory_claims_privacy_class",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_claims_student_subject",
        "memory_claims",
        ["student_id", "subject_type", "subject_id", "created_at"],
    )

    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("source_event_id", sa.UUID(), nullable=True),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_default(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_default(), nullable=False),
        sa.Column("privacy_class", sa.String(length=2), server_default="P1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "privacy_class IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_memory_evidence_privacy_class",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_evidence_student_occurred",
        "memory_evidence",
        ["student_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_memory_evidence_source_event",
        "memory_evidence",
        ["source_event_id"],
    )

    op.create_table(
        "memory_claim_evidence",
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("relation", sa.String(length=20), server_default="supports", nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["memory_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["memory_evidence.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id"),
    )


def downgrade() -> None:
    op.drop_table("memory_claim_evidence")
    op.drop_index("ix_memory_evidence_source_event", table_name="memory_evidence")
    op.drop_index("ix_memory_evidence_student_occurred", table_name="memory_evidence")
    op.drop_table("memory_evidence")
    op.drop_index("ix_memory_claims_student_subject", table_name="memory_claims")
    op.drop_table("memory_claims")

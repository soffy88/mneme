"""Add versioned cognitive, evidence and policy closure fields.

The migration is additive.  Existing event, memory and policy readers remain
valid because all new columns have compatible defaults or are nullable.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4a6b7c8d9e01"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEVELS = "('contract', 'offline', 'observational', 'randomized', 'commercial')"
_PHASES = "('practice', 'immediate_test', 'delayed_test', 'near_transfer', 'far_transfer', 'independent_no_ai', 'baseline', 'delayed')"


def _jsonb_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column("learning_events", sa.Column("evaluation_phase", sa.String(32)))
    op.create_check_constraint(
        "ck_learning_events_evaluation_phase",
        "learning_events",
        f"evaluation_phase IS NULL OR evaluation_phase IN {_PHASES}",
    )

    for name, column in (
        ("knowledge_ref", sa.Column("knowledge_ref", sa.String(100))),
        ("source", sa.Column("source", sa.String(64))),
        ("weight", sa.Column("weight", sa.Float())),
        ("confidence", sa.Column("confidence", sa.Float())),
        ("model_version", sa.Column("model_version", sa.String(120))),
        ("verifier_version", sa.Column("verifier_version", sa.String(120))),
        (
            "evidence_level",
            sa.Column("evidence_level", sa.String(16), server_default="contract", nullable=False),
        ),
    ):
        op.add_column("memory_evidence", column)
    op.create_check_constraint(
        "ck_memory_evidence_evidence_level",
        "memory_evidence",
        f"evidence_level IN {_LEVELS}",
    )

    for column in (
        sa.Column("knowledge_ref", sa.String(100)),
        sa.Column("claim_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("computed_at", sa.DateTime(timezone=True)),
        sa.Column("uncertainty", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("evidence_level", sa.String(16), server_default="contract", nullable=False),
    ):
        op.add_column("memory_claims", column)
    op.create_check_constraint(
        "ck_memory_claims_evidence_level",
        "memory_claims",
        f"evidence_level IN {_LEVELS}",
    )

    op.create_table(
        "policy_decisions",
        sa.Column("decision_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_action", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_version", sa.String(120), nullable=False),
        sa.Column("policy_version", sa.String(120), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_utility", sa.Float()),
        sa.Column("exploration_flag", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fallback_reason", sa.Text()),
        sa.Column("evidence_level", sa.String(16), server_default="contract", nullable=False),
        sa.Column("trace_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"evidence_level IN {_LEVELS}",
            name="ck_policy_decisions_evidence_level",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_policy_decisions_student_timestamp",
        "policy_decisions",
        ["student_id", "timestamp", "decision_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_policy_decisions_student_timestamp", table_name="policy_decisions")
    op.drop_table("policy_decisions")
    op.drop_constraint("ck_memory_claims_evidence_level", "memory_claims", type_="check")
    for name in ("evidence_level", "uncertainty", "computed_at", "claim_value", "knowledge_ref"):
        op.drop_column("memory_claims", name)
    op.drop_constraint("ck_memory_evidence_evidence_level", "memory_evidence", type_="check")
    for name in ("evidence_level", "verifier_version", "model_version", "confidence", "weight", "source", "knowledge_ref"):
        op.drop_column("memory_evidence", name)
    op.drop_constraint("ck_learning_events_evaluation_phase", "learning_events", type_="check")
    op.drop_column("learning_events", "evaluation_phase")

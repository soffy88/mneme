"""Add product outcome projections for the existing learning-event pipeline.

These are append-only/query projections.  They do not replace LearningEvent,
store raw answers, or change cognitive state.  Both tables are student-linked
and therefore are included in the purge inventory.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4d9e0f123456"
down_revision: Union[str, Sequence[str], None] = "4c8d9e0f1234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONTAMINATION = (
    "'CLEAN', 'AI_ASSISTED', 'HINT_ASSISTED', 'ANSWER_EXPOSED', 'INVALIDATED', 'UNKNOWN'"
)


def upgrade() -> None:
    op.create_table(
        "policy_outcome_links",
        sa.Column("link_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("action_event_id", sa.UUID(), nullable=False),
        sa.Column("outcome_event_id", sa.UUID(), nullable=False),
        sa.Column("latency_seconds", sa.Float()),
        sa.Column("eligible_for_evaluation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("contamination_status", sa.String(16), server_default="UNKNOWN", nullable=False),
        sa.Column("trace_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"contamination_status IN ({_CONTAMINATION})",
            name="ck_policy_outcome_link_contamination",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("link_id"),
        sa.UniqueConstraint(
            "decision_id",
            "action_event_id",
            "outcome_event_id",
            name="uq_policy_outcome_link_edge",
        ),
    )
    op.create_index(
        "ix_policy_outcome_links_student",
        "policy_outcome_links",
        ["student_id", "created_at"],
    )

    op.create_table(
        "learning_outcome_ledger",
        sa.Column("ledger_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("action_event_id", sa.UUID(), nullable=False),
        sa.Column("outcome_event_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_ref", sa.String(100)),
        sa.Column("state_version", sa.String(120)),
        sa.Column("policy_version", sa.String(120)),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evaluation_phase", sa.String(32)),
        sa.Column("evaluation_kind", sa.String(20), server_default="descriptive", nullable=False),
        sa.Column("contamination_status", sa.String(16), server_default="UNKNOWN", nullable=False),
        sa.Column("protocol_id", sa.String(120)),
        sa.Column("protocol_version", sa.String(40)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synthetic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"contamination_status IN ({_CONTAMINATION})",
            name="ck_learning_outcome_ledger_contamination",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("ledger_id"),
    )
    op.create_index(
        "ix_learning_outcome_ledger_student_time",
        "learning_outcome_ledger",
        ["student_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_outcome_ledger_student_time",
        table_name="learning_outcome_ledger",
    )
    op.drop_table("learning_outcome_ledger")
    op.drop_index("ix_policy_outcome_links_student", table_name="policy_outcome_links")
    op.drop_table("policy_outcome_links")

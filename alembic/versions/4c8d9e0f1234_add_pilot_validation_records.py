"""Add auditable real-world validation records.

The tables contain only protocol, cohort, assignment, consent status and
measurement metadata.  No raw answers or unnecessary PII are introduced.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4c8d9e0f1234"
down_revision: Union[str, Sequence[str], None] = "4b7c8d9e0f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def _jsonb_list_default() -> sa.TextClause:
    return sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.drop_constraint(
        "ck_learning_events_evaluation_phase", "learning_events", type_="check"
    )
    op.create_check_constraint(
        "ck_learning_events_evaluation_phase",
        "learning_events",
        "evaluation_phase IS NULL OR evaluation_phase IN ('practice', 'immediate_test', 'delayed_test', 'delayed_7d', 'delayed_30d', 'near_transfer', 'far_transfer', 'independent_no_ai', 'baseline', 'delayed')",
    )
    op.create_table(
        "pilot_enrollments",
        sa.Column("enrollment_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("protocol_id", sa.String(120), nullable=False),
        sa.Column("protocol_version", sa.String(40), nullable=False),
        sa.Column("cohort_id", sa.String(120), nullable=False),
        sa.Column("consent_status", sa.String(16), server_default="UNKNOWN", nullable=False),
        sa.Column("consent_version", sa.String(40)),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "consent_status IN ('UNKNOWN', 'NOT_REQUIRED', 'PENDING', 'GRANTED', 'REVOKED')",
            name="ck_pilot_enrollments_consent_status",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("enrollment_id"),
        sa.UniqueConstraint(
            "student_id", "protocol_id", "protocol_version",
            name="uq_pilot_enrollments_student_protocol",
        ),
    )
    op.create_index(
        "ix_pilot_enrollments_cohort", "pilot_enrollments", ["cohort_id", "protocol_id"]
    )

    op.create_table(
        "pilot_assignments",
        sa.Column("assignment_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("enrollment_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("protocol_id", sa.String(120), nullable=False),
        sa.Column("protocol_version", sa.String(40), nullable=False),
        sa.Column("cohort_id", sa.String(120), nullable=False),
        sa.Column("arm", sa.String(80), nullable=False),
        sa.Column("assignment_method", sa.String(120), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["pilot_enrollments.enrollment_id"]),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("assignment_id"),
        sa.UniqueConstraint("enrollment_id", name="uq_pilot_assignments_enrollment"),
    )

    op.create_table(
        "pilot_measurement_schedules",
        sa.Column("schedule_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("enrollment_id", sa.UUID(), nullable=False),
        sa.Column("protocol_id", sa.String(120), nullable=False),
        sa.Column("protocol_version", sa.String(40), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("measurement_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_open_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), server_default="SCHEDULED", nullable=False),
        sa.Column("evidence_event_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_list_default(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'AVAILABLE', 'COMPLETED', 'MISSED', 'INVALIDATED')",
            name="ck_pilot_measurement_status",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["enrollment_id"], ["pilot_enrollments.enrollment_id"]),
        sa.PrimaryKeyConstraint("schedule_id"),
        sa.UniqueConstraint(
            "student_id", "protocol_id", "protocol_version", "phase",
            name="uq_pilot_measurement_student_phase",
        ),
    )
    op.create_index(
        "ix_pilot_measurement_due", "pilot_measurement_schedules",
        ["status", "measurement_due_at"],
    )

    op.create_table(
        "pilot_analysis_artifacts",
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("protocol_id", sa.String(120), nullable=False),
        sa.Column("protocol_version", sa.String(40), nullable=False),
        sa.Column("cohort_id", sa.String(120), nullable=False),
        sa.Column("code_sha", sa.String(128), nullable=False),
        sa.Column("analysis_version", sa.String(120), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_default(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), server_default=_jsonb_default(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
    )

    op.create_table(
        "pilot_evidence_registry",
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("evidence_level", sa.String(16), nullable=False),
        sa.Column("protocol_id", sa.String(120)),
        sa.Column("cohort_id", sa.String(120)),
        sa.Column("data_cutoff", sa.DateTime(timezone=True)),
        sa.Column("analysis_version", sa.String(120), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("analysis_artifact_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "evidence_level IN ('contract', 'offline', 'observational', 'randomized', 'commercial')",
            name="ck_pilot_evidence_registry_level",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUPPORTED', 'NOT_SUPPORTED', 'INCONCLUSIVE', 'RETRACTED')",
            name="ck_pilot_evidence_registry_status",
        ),
        sa.ForeignKeyConstraint(["analysis_artifact_id"], ["pilot_analysis_artifacts.artifact_id"]),
        sa.PrimaryKeyConstraint("evidence_id"),
    )


def downgrade() -> None:
    op.drop_table("pilot_evidence_registry")
    op.drop_table("pilot_analysis_artifacts")
    op.drop_index("ix_pilot_measurement_due", table_name="pilot_measurement_schedules")
    op.drop_table("pilot_measurement_schedules")
    op.drop_table("pilot_assignments")
    op.drop_index("ix_pilot_enrollments_cohort", table_name="pilot_enrollments")
    op.drop_table("pilot_enrollments")
    op.drop_constraint(
        "ck_learning_events_evaluation_phase", "learning_events", type_="check"
    )
    op.create_check_constraint(
        "ck_learning_events_evaluation_phase",
        "learning_events",
        "evaluation_phase IS NULL OR evaluation_phase IN ('practice', 'immediate_test', 'delayed_test', 'near_transfer', 'far_transfer', 'independent_no_ai', 'baseline', 'delayed')",
    )

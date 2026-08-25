"""add explicit Tutor/independent evaluation signals

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-25

The fields are nullable by design: historical interaction rows are unknown,
not automatically AI-assisted or independent.  They make no-AI and delayed
evaluation claims auditable without changing the mastery write path.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interaction_events",
        sa.Column("tutor_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "interaction_events",
        sa.Column("ai_assisted", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "interaction_events",
        sa.Column("independent_mode", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "interaction_events",
        sa.Column("evaluation_phase", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "interaction_events",
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    # Preserve historical event chronology.  Do not let migration time become
    # the receipt time of old rows and accidentally exclude them from holdout.
    op.execute(
        "UPDATE interaction_events SET received_at = occurred_at "
        "WHERE received_at IS NULL"
    )
    op.create_index(
        "ix_interaction_events_evaluation_signals",
        "interaction_events",
        ["source", "independent_mode", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interaction_events_evaluation_signals",
        table_name="interaction_events",
    )
    op.drop_column("interaction_events", "received_at")
    op.drop_column("interaction_events", "evaluation_phase")
    op.drop_column("interaction_events", "independent_mode")
    op.drop_column("interaction_events", "ai_assisted")
    op.drop_column("interaction_events", "tutor_mode")

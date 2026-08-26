"""Keep Evaluation OS v2 baseline/delayed labels parseable during transition."""

from typing import Sequence, Union

from alembic import op


revision: str = "4b7c8d9e0f12"
down_revision: Union[str, Sequence[str], None] = "4a6b7c8d9e01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PHASES = "('practice', 'immediate_test', 'delayed_test', 'near_transfer', 'far_transfer', 'independent_no_ai', 'baseline', 'delayed')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_learning_events_evaluation_phase", "learning_events", type_="check"
    )
    op.create_check_constraint(
        "ck_learning_events_evaluation_phase",
        "learning_events",
        f"evaluation_phase IS NULL OR evaluation_phase IN {_PHASES}",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_learning_events_evaluation_phase", "learning_events", type_="check"
    )
    op.create_check_constraint(
        "ck_learning_events_evaluation_phase",
        "learning_events",
        "evaluation_phase IS NULL OR evaluation_phase IN ('practice', 'immediate_test', 'delayed_test', 'near_transfer', 'far_transfer', 'independent_no_ai')",
    )

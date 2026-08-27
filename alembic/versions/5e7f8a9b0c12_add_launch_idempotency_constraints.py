"""Add database uniqueness for outcome projection retries."""

from typing import Sequence, Union

from alembic import op

revision: str = "5e7f8a9b0c12"
down_revision: Union[str, None] = "4d9e0f123456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_learning_outcome_ledger_edge",
        "learning_outcome_ledger",
        ["decision_id", "action_event_id", "outcome_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_learning_outcome_ledger_edge",
        "learning_outcome_ledger",
        type_="unique",
    )

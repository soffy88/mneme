"""add_mastery_snapshot_unique_constraint

Revision ID: 7a060dea2207
Revises: 37dca26607ff
Create Date: 2026-06-14 09:07:21.481625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a060dea2207'
down_revision: Union[str, Sequence[str], None] = '37dca26607ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_mastery_snapshots_student_kc_month",
        "mastery_snapshots",
        ["student_id", "knowledge_point", "snapshot_month"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mastery_snapshots_student_kc_month",
        "mastery_snapshots",
        type_="unique",
    )

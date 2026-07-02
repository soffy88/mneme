"""add step_analysis to wrong_questions

Revision ID: e2d7c40a91b3
Revises: a3c9e51fb217
Create Date: 2026-07-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e2d7c40a91b3"
down_revision: Union[str, Sequence[str], None] = "a3c9e51fb217"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 拍卷过程批改（T.6）——wrong_questions.step_analysis
    （JSONB, nullable）：{student_steps, step_verdicts:[{step_text,verdict}],
    first_wrong_step(0-based|null)}，由 verify_step 确定性链产出。"""
    op.add_column(
        "wrong_questions",
        sa.Column("step_analysis", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("wrong_questions", "step_analysis")

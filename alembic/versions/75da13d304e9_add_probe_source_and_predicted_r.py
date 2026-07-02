"""add probe source and predicted_r

Revision ID: 75da13d304e9
Revises: bfeae2b93814
Create Date: 2026-07-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "75da13d304e9"
down_revision: Union[str, Sequence[str], None] = "bfeae2b93814"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 保留探针（T.2）——interactionsource 加 'probe' 值 +
    interaction_events.predicted_r（作答时 FSRS 预测可提取性 R，nullable）。"""
    # PG12+ 允许在事务内 ADD VALUE（同事务内不使用该值即可）
    op.execute("ALTER TYPE interactionsource ADD VALUE IF NOT EXISTS 'probe'")
    op.add_column(
        "interaction_events", sa.Column("predicted_r", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema。PostgreSQL 不支持删 enum value，'probe' 留存无害。"""
    op.drop_column("interaction_events", "predicted_r")

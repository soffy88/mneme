"""add freezes_available to streaks (P1-10 留存激励)

Revision ID: f4b1c2d3e5a6
Revises: e2d7c40a91b3
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4b1c2d3e5a6"
down_revision: Union[str, Sequence[str], None] = "e2d7c40a91b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """streaks.freezes_available：连胜保护次数（默认 2）。缺一天且有护盾则自动
    消耗 1 张护盾保住连胜；护盾靠持续检索里程碑赚取（绑学习过程，非裸买）。"""
    op.add_column(
        "streaks",
        sa.Column(
            "freezes_available",
            sa.Integer(),
            server_default="2",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("streaks", "freezes_available")

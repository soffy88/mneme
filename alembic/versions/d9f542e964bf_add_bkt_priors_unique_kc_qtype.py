"""add_bkt_priors_unique_kc_qtype

Revision ID: d9f542e964bf
Revises: 7a060dea2207
Create Date: 2026-06-14 09:12:43.981080

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd9f542e964bf'
down_revision: Union[str, Sequence[str], None] = '7a060dea2207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_bkt_priors_kc_qtype",
        "bkt_priors",
        ["knowledge_point", "question_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_bkt_priors_kc_qtype", "bkt_priors", type_="unique")

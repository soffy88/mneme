"""add_soft_prerequisites

Revision ID: 737a1fcd01b1
Revises: 0309de38ca92
Create Date: 2026-07-09 07:18:38.343738

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "737a1fcd01b1"
down_revision: Union[str, Sequence[str], None] = "0309de38ca92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_units",
        sa.Column(
            "soft_prerequisites",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_units", "soft_prerequisites")

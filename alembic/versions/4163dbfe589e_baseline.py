"""baseline

Revision ID: 4163dbfe589e
Revises: 
Create Date: 2026-06-13 01:58:54.390297

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '4163dbfe589e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

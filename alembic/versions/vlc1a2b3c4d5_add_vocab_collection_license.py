"""vocabulary_collections / vocabulary_import_batches 加来源许可与地址

Revision ID: vlc1a2b3c4d5
Revises: qrc1a2b3c4d5
Create Date: 2026-10-18

纯增量：两张表各加可空列 license、source_url，不改不删既有列。
lilinji/English 词表导入器写 'CC BY-NC-SA 4.0' / 'https://github.com/lilinji/English'。
"""

from alembic import op
import sqlalchemy as sa

revision = "vlc1a2b3c4d5"
down_revision = "qrc1a2b3c4d5"
branch_labels = None
depends_on = None

_TABLES = ("vocabulary_collections", "vocabulary_import_batches")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("license", sa.String(100), nullable=True))
        op.add_column(t, sa.Column("source_url", sa.String(500), nullable=True))


def downgrade() -> None:
    for t in _TABLES:
        op.drop_column(t, "source_url")
        op.drop_column(t, "license")

"""add_textbook_files_highlights_reading_notes

Revision ID: dff2ec15ff91
Revises: 4ebc8f4ef067
Create Date: 2026-06-21 04:49:16.885613

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'dff2ec15ff91'
down_revision: Union[str, Sequence[str], None] = '4ebc8f4ef067'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. textbook_files ──────────────────────────────────────────
    op.create_table(
        'textbook_files',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('textbook_id', sa.String(50), nullable=True),
        sa.Column('owner_student_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(10), nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('uploaded_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['textbook_id'], ['textbooks.id'], name='fk_tf_textbook'),
        sa.ForeignKeyConstraint(['owner_student_id'], ['users.id'], name='fk_tf_owner'),
    )
    op.create_index('ix_tf_textbook_id', 'textbook_files', ['textbook_id'])
    op.create_index('ix_tf_owner_student_id', 'textbook_files', ['owner_student_id'])

    # ── 2. highlights ──────────────────────────────────────────────
    op.create_table(
        'highlights',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('student_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_id', sa.String(50), nullable=False),
        sa.Column('color', sa.String(10), server_default='yellow', nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('location_json', JSONB, server_default='{}', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name='fk_hl_student'),
        sa.ForeignKeyConstraint(['file_id'], ['textbook_files.id'], name='fk_hl_file'),
    )
    op.create_index('ix_highlights_student_file', 'highlights', ['student_id', 'file_id'])

    # ── 3. reading_notes ───────────────────────────────────────────
    op.create_table(
        'reading_notes',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('student_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_id', sa.String(50), nullable=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('highlight_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name='fk_rn_student'),
        sa.ForeignKeyConstraint(['file_id'], ['textbook_files.id'], name='fk_rn_file'),
        sa.ForeignKeyConstraint(['highlight_id'], ['highlights.id'], name='fk_rn_highlight'),
    )
    op.create_index('ix_reading_notes_student_file', 'reading_notes', ['student_id', 'file_id'])


def downgrade() -> None:
    op.drop_table('reading_notes')
    op.drop_table('highlights')
    op.drop_table('textbook_files')

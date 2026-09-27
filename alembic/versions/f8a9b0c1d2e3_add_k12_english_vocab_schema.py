"""add_k12_english_vocab_schema

Revision ID: f8a9b0c1d2e3
Revises: f7e4a5b6c9d0
Create Date: 2024-05-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f8a9b0c1d2e3'
down_revision = "7b2c3d4e5f6a"
branch_labels = None
depends_on = None

def upgrade():
    # add columns to vocabulary_items
    op.add_column('vocabulary_items', sa.Column('language', sa.String(10), server_default='en', nullable=False))
    op.add_column('vocabulary_items', sa.Column('display_form', sa.String(100), nullable=True))
    op.add_column('vocabulary_items', sa.Column('normalized_form', sa.String(100), nullable=True))
    op.add_column('vocabulary_items', sa.Column('lexeme_type', sa.String(20), server_default='WORD', nullable=False))
    op.add_column('vocabulary_items', sa.Column('canonical_meaning', sa.Text(), nullable=True))
    op.add_column('vocabulary_items', sa.Column('phonetic_uk', sa.String(100), nullable=True))
    op.add_column('vocabulary_items', sa.Column('phonetic_us', sa.String(100), nullable=True))
    op.add_column('vocabulary_items', sa.Column('phonetic_generic', sa.String(100), nullable=True))
    op.add_column('vocabulary_items', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    
    # create vocabulary_collections
    op.create_table('vocabulary_collections',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('source_id', sa.String(100), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('publisher', sa.String(100), nullable=True),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('grade', sa.Integer(), nullable=True),
        sa.Column('semester', sa.Integer(), nullable=True),
        sa.Column('edition', sa.String(50), nullable=True),
        sa.Column('curriculum_year', sa.Integer(), nullable=True),
        sa.Column('book_type', sa.String(50), nullable=True),
        sa.Column('exam_type', sa.String(50), nullable=True),
        sa.Column('region', sa.String(100), nullable=True),
        sa.Column('source_relative_path', sa.String(500), nullable=True),
        sa.Column('source_file_sha256', sa.String(64), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True)
    )

    # create vocabulary_collection_memberships
    op.create_table('vocabulary_collection_memberships',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('collection_id', sa.String(100), nullable=False),
        sa.Column('vocabulary_item_id', sa.String(100), nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=True),
        sa.Column('source_definition', sa.Text(), nullable=True),
        sa.Column('source_pos', sa.String(50), nullable=True),
        sa.Column('source_phonetic_uk', sa.String(100), nullable=True),
        sa.Column('source_phonetic_us', sa.String(100), nullable=True),
        sa.Column('source_phonetic_generic', sa.String(100), nullable=True),
        sa.Column('source_sentence', sa.Text(), nullable=True),
        sa.Column('source_relative_path', sa.String(500), nullable=True),
        sa.Column('source_row', sa.Integer(), nullable=True),
        sa.Column('source_entry_key', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['collection_id'], ['vocabulary_collections.id'], ),
        sa.ForeignKeyConstraint(['vocabulary_item_id'], ['vocabulary_items.id'], ),
        sa.UniqueConstraint('collection_id', 'vocabulary_item_id', name='uq_vocab_membership')
    )

    # create vocabulary_import_batches
    op.create_table('vocabulary_import_batches',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('source_name', sa.String(100), nullable=True),
        sa.Column('source_commit_sha', sa.String(40), nullable=True),
        sa.Column('parser_version', sa.String(20), nullable=True),
        sa.Column('mode', sa.String(20), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('files_total', sa.Integer(), nullable=True),
        sa.Column('files_parsed', sa.Integer(), nullable=True),
        sa.Column('files_failed', sa.Integer(), nullable=True),
        sa.Column('rows_total', sa.Integer(), nullable=True),
        sa.Column('rows_valid', sa.Integer(), nullable=True),
        sa.Column('rows_skipped', sa.Integer(), nullable=True),
        sa.Column('rows_invalid', sa.Integer(), nullable=True),
        sa.Column('vocab_created', sa.Integer(), nullable=True),
        sa.Column('vocab_existing', sa.Integer(), nullable=True),
        sa.Column('collections_created', sa.Integer(), nullable=True),
        sa.Column('memberships_created', sa.Integer(), nullable=True),
        sa.Column('memberships_updated', sa.Integer(), nullable=True),
        sa.Column('duplicates_in_collection', sa.Integer(), nullable=True),
        sa.Column('phrases', sa.Integer(), nullable=True),
        sa.Column('words', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('report_path', sa.String(500), nullable=True)
    )

def downgrade():
    op.drop_table('vocabulary_import_batches')
    op.drop_table('vocabulary_collection_memberships')
    op.drop_table('vocabulary_collections')
    
    op.drop_column('vocabulary_items', 'updated_at')
    op.drop_column('vocabulary_items', 'phonetic_generic')
    op.drop_column('vocabulary_items', 'phonetic_us')
    op.drop_column('vocabulary_items', 'phonetic_uk')
    op.drop_column('vocabulary_items', 'canonical_meaning')
    op.drop_column('vocabulary_items', 'lexeme_type')
    op.drop_column('vocabulary_items', 'normalized_form')
    op.drop_column('vocabulary_items', 'display_form')
    op.drop_column('vocabulary_items', 'language')


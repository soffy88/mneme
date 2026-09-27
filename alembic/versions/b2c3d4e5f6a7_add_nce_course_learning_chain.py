"""add_nce_course_learning_chain

Revision ID: a1b2c3d4e5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-09-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('courses',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('series', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('source_id', sa.String(100), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table('course_books',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('course_id', sa.String(100), nullable=False),
        sa.Column('book_key', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('level', sa.String(50), nullable=True),
        sa.Column('edition', sa.String(50), nullable=False),
        sa.Column('source_url', sa.String(500), nullable=True),
        sa.Column('source_hash', sa.String(64), nullable=True),
        sa.Column('source_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.UniqueConstraint('course_id', 'edition', 'book_key', name='uq_book_course_edition_key')
    )

    op.create_table('lessons',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('book_id', sa.String(100), nullable=False),
        sa.Column('lesson_key', sa.String(200), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=False),
        sa.Column('audio_uri', sa.String(500), nullable=True),
        sa.Column('audio_hash', sa.String(64), nullable=True),
        sa.Column('audio_duration_ms', sa.Integer(), nullable=True),
        sa.Column('lrc_uri', sa.String(500), nullable=True),
        sa.Column('lrc_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['book_id'], ['course_books.id'], ),
        sa.UniqueConstraint('book_id', 'lesson_key', name='uq_lesson_book_key')
    )

    op.create_table('timed_sentences',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('lesson_id', sa.String(100), nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=False),
        sa.Column('end_ms', sa.Integer(), nullable=True),
        sa.Column('english_text', sa.Text(), nullable=True),
        sa.Column('chinese_text', sa.Text(), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('source_line', sa.Integer(), nullable=True),
        sa.Column('source_entry_key', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
        sa.UniqueConstraint('lesson_id', 'source_entry_key', name='uq_sentence_lesson_entry')
    )

    op.create_table('lesson_vocabulary_memberships',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('lesson_id', sa.String(100), nullable=False),
        sa.Column('vocabulary_item_id', sa.String(100), nullable=False),
        sa.Column('first_sentence_id', sa.String(100), nullable=True),
        sa.Column('first_occurrence_order', sa.Integer(), nullable=True),
        sa.Column('occurrence_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('source_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
        sa.ForeignKeyConstraint(['vocabulary_item_id'], ['vocabulary_items.id'], ),
        sa.ForeignKeyConstraint(['first_sentence_id'], ['timed_sentences.id'], ),
        sa.UniqueConstraint('lesson_id', 'vocabulary_item_id', name='uq_lesson_vocab')
    )

    op.create_table('sentence_vocabulary_occurrences',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('sentence_id', sa.String(100), nullable=False),
        sa.Column('vocabulary_item_id', sa.String(100), nullable=False),
        sa.Column('occurrence_index', sa.Integer(), nullable=False),
        sa.Column('token_start', sa.Integer(), nullable=True),
        sa.Column('token_end', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['sentence_id'], ['timed_sentences.id'], ),
        sa.ForeignKeyConstraint(['vocabulary_item_id'], ['vocabulary_items.id'], ),
        sa.UniqueConstraint('sentence_id', 'vocabulary_item_id', 'occurrence_index', name='uq_sentence_vocab_occurrence')
    )


def downgrade():
    op.drop_table('sentence_vocabulary_occurrences')
    op.drop_table('lesson_vocabulary_memberships')
    op.drop_table('timed_sentences')
    op.drop_table('lessons')
    op.drop_table('course_books')
    op.drop_table('courses')

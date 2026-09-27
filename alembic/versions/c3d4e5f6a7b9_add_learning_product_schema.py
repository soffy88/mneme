"""add_learning_product_schema

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b9'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('learning_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject', sa.String(20), server_default='english', nullable=False),
        sa.Column('primary_scope', sa.String(20), server_default='K12_SYNC', nullable=False),
        sa.Column('primary_collection_id', sa.String(100), nullable=True),
        sa.Column('current_book_id', sa.String(100), nullable=True),
        sa.Column('current_lesson_id', sa.String(100), nullable=True),
        sa.Column('exam_target', sa.String(20), server_default='NONE', nullable=False),
        sa.Column('nce_support_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('daily_new_word_target', sa.Integer(), server_default='10', nullable=False),
        sa.Column('daily_review_target', sa.Integer(), server_default='20', nullable=False),
        sa.Column('status', sa.String(20), server_default='ACTIVE', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['primary_collection_id'], ['vocabulary_collections.id'], ),
        sa.ForeignKeyConstraint(['current_book_id'], ['course_books.id'], ),
        sa.ForeignKeyConstraint(['current_lesson_id'], ['lessons.id'], )
    )
    op.create_index('uq_learning_plan_active', 'learning_plans', ['user_id', 'subject'],
                    unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))

    op.create_table('learning_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('learning_plan_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('lesson_id', sa.String(100), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('items_presented', sa.Integer(), server_default='0', nullable=False),
        sa.Column('items_correct', sa.Integer(), server_default='0', nullable=False),
        sa.Column('items_incorrect', sa.Integer(), server_default='0', nullable=False),
        sa.Column('new_items', sa.Integer(), server_default='0', nullable=False),
        sa.Column('review_items', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['learning_plan_id'], ['learning_plans.id'], ),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], )
    )

    op.create_table('learning_session_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vocabulary_item_id', sa.String(100), nullable=False),
        sa.Column('task_type', sa.String(20), nullable=False),
        sa.Column('context_source', sa.String(20), server_default='TEXTBOOK', nullable=False),
        sa.Column('sentence_id', sa.String(100), nullable=True),
        sa.Column('state', sa.String(20), server_default='PENDING', nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('interaction_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['learning_sessions.id'], ),
        sa.ForeignKeyConstraint(['vocabulary_item_id'], ['vocabulary_items.id'], ),
        sa.ForeignKeyConstraint(['sentence_id'], ['timed_sentences.id'], ),
        sa.UniqueConstraint('session_id', 'sequence', name='uq_session_item_sequence')
    )

    op.create_table('user_lesson_progress',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lesson_id', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), server_default='not_started', nullable=False),
        sa.Column('vocab_total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('vocab_started', sa.Integer(), server_default='0', nullable=False),
        sa.Column('vocab_mastered', sa.Integer(), server_default='0', nullable=False),
        sa.Column('lesson_check_score', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
        sa.UniqueConstraint('user_id', 'lesson_id', name='uq_user_lesson_progress')
    )

    op.create_table('user_book_progress',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('book_id', sa.String(100), nullable=False),
        sa.Column('completed_lessons', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_lessons', sa.Integer(), server_default='0', nullable=False),
        sa.Column('book_vocab_mastered', sa.Integer(), server_default='0', nullable=False),
        sa.Column('book_vocab_total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['book_id'], ['course_books.id'], ),
        sa.UniqueConstraint('user_id', 'book_id', name='uq_user_book_progress')
    )


def downgrade():
    op.drop_table('user_book_progress')
    op.drop_table('user_lesson_progress')
    op.drop_table('learning_session_items')
    op.drop_table('learning_sessions')
    op.drop_table('learning_plans')

"""add word_atlas_fsrs_cards and vocab_media_availability

Word Atlas 集成-2 接线：FSRS 卡片状态存储 + 媒体可用性附表。

- word_atlas_fsrs_cards：每（学生，词）一张卡，分列与
  services/wordatlas_fsrs.to_dict 的 fsrs_card_json 口径一致
  （stability/difficulty/due/last_review/review_count），外加
  applied_review_ids（同轮重答幂等 id 集）。vocab_units 仍是只读
  参考表，进度绝不写回 vocab_units；BKT 掌握裁决也不在此表。
- vocab_media_availability：集成-3 方案原样落盘（附表，不在
  vocab_units 上加列；6 布尔位 + media_mask 生成列，
  img=1/thumb=2/uk=4/us=8/ex=16/ex2=32）+ 联查视图
  vocab_units_with_media。数据填充由
  scripts/fill_word_atlas_media_availability.py 以
  PUBLIC_MANIFEST.json 为准执行，不在本迁移里写死数据。

Revision ID: f9a1b2c3d4e5
Revises: rin1a2b3c4d5
Create Date: 2026-10-26

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f9a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'rin1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MEDIA_MASK_EXPR = (
    "(CASE WHEN has_img THEN 1 ELSE 0 END)"
    " + (CASE WHEN has_thumb THEN 2 ELSE 0 END)"
    " + (CASE WHEN has_audio_uk THEN 4 ELSE 0 END)"
    " + (CASE WHEN has_audio_us THEN 8 ELSE 0 END)"
    " + (CASE WHEN has_audio_ex THEN 16 ELSE 0 END)"
    " + (CASE WHEN has_audio_ex2 THEN 32 ELSE 0 END)"
)


def upgrade() -> None:
    op.create_table(
        'word_atlas_fsrs_cards',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('student_key', sa.Text(), nullable=False,
                  server_default=sa.text("''")),
        sa.Column('vocab_id', sa.Text(), nullable=False),
        sa.Column('stability', sa.Float(), nullable=True),
        sa.Column('difficulty', sa.Float(), nullable=True),
        sa.Column('due', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_review', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_count', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('fsrs_card_json', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column('applied_review_ids', postgresql.ARRAY(sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['vocab_id'], ['vocab_units.id']),
        sa.UniqueConstraint('student_key', 'vocab_id',
                            name='uq_word_atlas_fsrs_cards_student_vocab'),
    )
    op.create_index('idx_word_atlas_fsrs_cards_due',
                    'word_atlas_fsrs_cards', ['due'])
    op.create_index('idx_word_atlas_fsrs_cards_vocab',
                    'word_atlas_fsrs_cards', ['vocab_id'])

    op.create_table(
        'vocab_media_availability',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('has_img', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('has_thumb', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('has_audio_uk', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('has_audio_us', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('has_audio_ex', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('has_audio_ex2', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('media_mask', sa.Integer(),
                  sa.Computed(_MEDIA_MASK_EXPR, persisted=True),
                  nullable=True),
        sa.Column('manifest_source', sa.Text(), nullable=False,
                  server_default=sa.text(
                      "'https://raw.githubusercontent.com/designfuchen/"
                      "word-atlas/main/PUBLIC_MANIFEST.json'")),
        sa.Column('manifest_checked_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['id'], ['vocab_units.id']),
    )
    op.create_index('idx_vocab_media_audio', 'vocab_media_availability',
                    ['has_audio_uk', 'has_audio_us'])

    op.execute(
        "CREATE OR REPLACE VIEW vocab_units_with_media AS"
        " SELECT v.*, m.has_img, m.has_thumb, m.has_audio_uk,"
        " m.has_audio_us, m.has_audio_ex, m.has_audio_ex2, m.media_mask"
        " FROM vocab_units v"
        " LEFT JOIN vocab_media_availability m ON m.id = v.id"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vocab_units_with_media")
    op.drop_index('idx_vocab_media_audio', table_name='vocab_media_availability')
    op.drop_table('vocab_media_availability')
    op.drop_index('idx_word_atlas_fsrs_cards_vocab',
                  table_name='word_atlas_fsrs_cards')
    op.drop_index('idx_word_atlas_fsrs_cards_due',
                  table_name='word_atlas_fsrs_cards')
    op.drop_table('word_atlas_fsrs_cards')

"""add item_difficulty to interaction_events

Revision ID: d049051a89f6
Revises: e7f3a9c21b04
Create Date: 2026-06-28 08:44:19.730937

BKT+IRT Phase 1：interaction_events 记录本次答题所用的题目难度 b∈[0,1]，
作为不可变事件日志的一部分（只增不改），供后续难度校准与 DKT 训练。

注：autogenerate 还检测到大量无关的既有 model↔DB 漂移（interaction_history /
error_tags 等运行时表、若干 index/FK、users.textbook_id），均与本变更无关，
故本 migration 仅保留 item_difficulty 一列的增/删，不触碰其它结构。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd049051a89f6'
down_revision: Union[str, Sequence[str], None] = 'e7f3a9c21b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interaction_events', sa.Column('item_difficulty', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('interaction_events', 'item_difficulty')

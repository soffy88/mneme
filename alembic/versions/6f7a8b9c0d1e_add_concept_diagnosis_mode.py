"""add_concept_diagnosis_mode

Revision ID: 6f7a8b9c0d1e
Revises: 890189c51106
Create Date: 2026-07-04

U.19：添加 SocraticMode enum 新值 concept_diagnosis，供物理概念优先范式
（FCI式诊断→认知冲突→计算迁移）第一步复用 socratic_sessions 表。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, Sequence[str], None] = "890189c51106"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres ADD VALUE IF NOT EXISTS requires PG ≥ 9.3; cannot be rolled back in a txn.
    op.execute("ALTER TYPE socraticmode ADD VALUE IF NOT EXISTS 'concept_diagnosis'")


def downgrade() -> None:
    # Postgres cannot remove enum values; downgrade is a no-op.
    pass

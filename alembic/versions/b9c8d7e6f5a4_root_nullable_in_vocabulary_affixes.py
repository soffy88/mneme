"""vocabulary_affixes.root 改可空

原迁移 f2a3b4c5d6e7 把 root 定义为 NOT NULL，隐含假设「每个可入门的词都必有
词根」。该假设不成立：一个词可能只被讲清「前缀 + 后缀」（careless = care +
less，其 care 被质量门判为平凡而落空），或散文只标了后缀。把 root 改成可空后，
这些分解可以诚实入库 —— format_affix_chain 本就支持缺失段位，而 NOT NULL
会让整个事务原子失败（0 行写入）。

index ix_vocab_affix_root 只索引非空值，可空不影响其可用性。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "vocabulary_affixes",
        "root",
        existing_type=sa.String(48),
        nullable=True,
    )


def downgrade() -> None:
    # 收紧回 NOT NULL 前必须先处理已有的 root IS NULL 行，否则迁移失败。
    op.execute("DELETE FROM vocabulary_affixes WHERE root IS NULL")
    op.alter_column(
        "vocabulary_affixes",
        "root",
        existing_type=sa.String(48),
        nullable=False,
    )
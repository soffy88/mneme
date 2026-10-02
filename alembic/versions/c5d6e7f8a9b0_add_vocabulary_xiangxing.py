"""象形9000 词条表。

象形9000（百词斩）的音标是**粗 ASCII 转写**（`['erb]`、`[e'bav]`），不是标准
IPA，与已有 ARPAbet（2,757 词）不是一回事 —— 展示层不能混用，故独立成表。

为什么不覆盖 vocabulary_items.meaning_cn：象形给的是词典**详尽义项**
（`novel` = 新奇的；有趣的），课标给的是「适合该学段的精简义项」（长篇小说）。
粒度不同而非冲突，与 vocabulary_collocations 同一处理原则。

`ownership_verified` 记录归属是否经**例句交叉验证**：象形体把形近/音近词分组，
组头列多个词、其下只有一条详情块，行相邻会静默错配。归属由「例句中实际出现
哪个词」判定，判不出即置 false —— 宁缺勿错。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vocabulary_xiangxing",
        # vocabulary_items.id 是 varchar(100)，FK 列必须同类型，否则建外键报错
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("vocabulary_item_id", sa.String(100), nullable=False),
        sa.Column("ipa_ascii", sa.String(48), nullable=True),
        sa.Column("pos", sa.String(16), nullable=True),
        sa.Column("meaning_cn", sa.Text(), nullable=False),
        sa.Column("example_en", sa.Text(), nullable=True),
        sa.Column("example_cn", sa.Text(), nullable=True),
        sa.Column("source_volume", sa.String(32), nullable=False),
        sa.Column("ownership_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["vocabulary_item_id"], ["vocabulary_items.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("vocabulary_item_id", name="uq_vocab_xiangxing_item"),
    )
    op.create_index("ix_vocab_xiangxing_item", "vocabulary_xiangxing", ["vocabulary_item_id"])
    op.create_index("ix_vocab_xiangxing_verified", "vocabulary_xiangxing", ["ownership_verified"])


def downgrade() -> None:
    op.drop_index("ix_vocab_xiangxing_verified", table_name="vocabulary_xiangxing")
    op.drop_index("ix_vocab_xiangxing_item", table_name="vocabulary_xiangxing")
    op.drop_table("vocabulary_xiangxing")
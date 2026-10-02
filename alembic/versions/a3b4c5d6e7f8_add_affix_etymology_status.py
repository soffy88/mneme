"""vocabulary_affixes.etymology_status —— 区分「词源事实」与「记忆联想」。

原表只存了分解本身，没存**这个分解凭什么可信**。而那379 条的来源是散文里
「词根/前缀/后缀」的标注，不是历史语言学：散文自身就常把词干/后缀写成「词根」
（`careless→less`、`chinese→ese`、`colour→col`）。按「单词深度记忆引擎 V2」自己的
标准（*"如果所谓'词根记忆法'只是人为联想，必须明确这是'记忆联想'，不是历史
词源"*），这些属于记忆联想，**不得与已校验词源同屏同权呈现**。

三档：
- `reference_confirmed` —— 与权威教学词根表一致（新东方词根词缀大全）。
  注意这是**教学参考级**权威（对比 OED/etymonline 的学术级），仍非学术词源。
- `mnemonic_association` —— 无参考佐证的人为联想，只能作记忆提示。
- `disputed` —— 与参考表冲突，留待人工判读，不静默采信任何一方。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vocabulary_affixes",
        sa.Column(
            "etymology_status",
            sa.String(24),
            nullable=False,
            server_default=sa.text("'mnemonic_association'"),
        ),
    )
    op.create_index(
        "ix_vocab_affix_ety_status", "vocabulary_affixes", ["etymology_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_vocab_affix_ety_status", table_name="vocabulary_affixes")
    op.drop_column("vocabulary_affixes", "etymology_status")
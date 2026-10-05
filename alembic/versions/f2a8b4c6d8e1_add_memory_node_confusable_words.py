"""add confusable_words to vocabulary_memory_nodes（易混词，spec §五 ⚠️ / §九）

Revision ID: f2a8b4c6d8e1
Revises: d7e8f9a0b1c2
Create Date: 2026-10-05

为什么加这一列，而不是新表：

`vocabulary_memory_nodes` 是**逐词生成**的产物（一个词一份），易混词同样是
「针对这个词、这一版生成里值得讲的那几个对照词」。放进节点表才符合单源红线 ——
词的联想层与它的易混对照属于同一份生成结果。建独立表会把「哪个对照词值得教」
变成全局事实，那是另一个量级的判断，且没有确定性来源。

类型选择 jsonb（不是 text）：`vocabulary_affixes` 等既有表已用 jsonb 存
结构化字段（`semantic_core` / `family_network` / `context_evidence`），
保持一致；且读取方要按 `word` 取值，不该在应用层反复 json.loads。

默认值 `'[]'::jsonb` 而不是 NULL：空列表与「还没生成」在这个表里不是两件事 ——
这列只由生成路径写入，没有「待填」状态。用 NULL 会让所有读取方多判一次。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8b4c6d8e1"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vocabulary_memory_nodes "
        "ADD COLUMN IF NOT EXISTS confusable_words jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vocabulary_memory_nodes DROP COLUMN IF EXISTS confusable_words")
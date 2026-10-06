"""add vocabulary_dictionary_glosses（词典来源释义，独立于教材与语料派生）

Revision ID: b3e9d1f5a7c2
Revises: f2a8b4c6d8e1
Create Date: 2026-10-05

为什么必须是**独立表**，不能复用 `vocabulary_derived_glosses`：

1. 该表有 CHECK 约束 `source_kind = 'corpus_llm'`，词典来源塞不进去；
2. 它的 `model` 列存的是生成模型（`Agents-A1`/`veya1.2`），词典来源没有模型；
3. `services/vocab_meaning` 把它的溯源串**硬编码**成「从真实语料句派生」——
   对词典来源那句话就是假的。溯源串必须是真的，否则「可回溯」这个卖点没了。

数据源：EchoType（MIT）`public/wordbooks/coca20000.json`。词表本身是**严格字母序**
（实测 `words == sorted(words)`），**不含任何词频信息** —— 文件名里的 COCA 只说明
「词表来自 COCA」，不代表保留了 rank。故本表**没有** frequency 列，别再加一个。

`source_ref` 存该词在源文件中的**行号**，用于回溯到具体那一条。

无学生数据，故不进 `services/purge_service._STUDENT_TABLES`。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b3e9d1f5a7c2"
down_revision: Union[str, Sequence[str], None] = "f2a8b4c6d8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vocabulary_dictionary_glosses (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            vocabulary_item_id varchar(100) NOT NULL
                               REFERENCES vocabulary_items(id) ON DELETE CASCADE,
            gloss              text NOT NULL,
            source             varchar(64) NOT NULL,
            source_ref         varchar(64),
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_vocab_dict_gloss_item UNIQUE (vocabulary_item_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vocab_dict_gloss_source "
        "ON vocabulary_dictionary_glosses (source)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vocabulary_dictionary_glosses")
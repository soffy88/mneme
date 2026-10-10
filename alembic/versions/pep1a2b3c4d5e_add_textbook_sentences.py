"""add textbook_sentences + 词表关联（教材真实语境句，Context Priority tier 1/2）

Revision ID: pep1a2b3c4d5e
Revises: b3e9d1f5a7c2
Create Date: 2026-10-06

## 为什么必须独立建表，不能复用 `timed_sentences`

`sentence_vocabulary_occurrences.sentence_id` 上有
`FOREIGN KEY ... REFERENCES timed_sentences(id)`。而 `timed_sentences` 是
**新概念英语专用**的表：每行挂在 `lesson_id` 上、带 `chinese_text` 与时间轴。
把教材句塞进去会让「NCE 语境」这一层名不副实，也会毁掉 tier 语义 ——
`services/vocab_context` 的 Context Priority **教材优先于 NCE**（tier 1/2 > 3），
教材句必须能被单独取到、单独标注来源。混进 `timed_sentences` 就再也分不开了。

所以走 Option A：新建 `textbook_sentences` + 自己的关联表
`textbook_sentence_occurrences`，并给 `vocab_context` 加 tier 1/2 查询。

## 这解的是实测出来的真瓶颈

2026-10-06 实测（核心 2,761 单词口径）：

| | 词数 |
|---|---|
| 有可用释义 | 2,732 |
| ├─ 且有语境句 → 记忆节点可生成 | 2,066 |
| └─ 但**无语境句** → 被 `retrieve_context` 挡在门外 | **666** |
| 无任何可用释义 | 29 |

`retrieve_context` 在 `has_context=False` 时**提前返回**，`to_payload()` 里根本
不带 `meaning` 字段。所以缺口不在释义（已从 776 补到 29），而在语境句。
教材句正是那 666 个词唯一**有出处、可回溯、且不是生成的**来源
（对照：EchoType 词表的英文例句实测是生成的，一律不进 `context_evidence`）。

## 数据来源与 `license_status`

来源是人教社电子教材（`book.pep.com.cn`，经 FreePEP 的 MIT 下载器取得页面图，
本机用 RapidOCR 识别）。**页图是 300 DPI 位图、零文本层**，所以 `textbook_files.
has_text_layer` 必须记 `false` —— 那是「怎么得到文本」的诚实记录。

`license_status` 是**故意加的**：让人教社正文（受版权保护、面向未成年人）
即便被接入，也能按整本教材精确下架 —— `DELETE FROM textbook_sentences WHERE
textbook_id = ...`，不需要数据迁移。当前值 `unlicensed`（未取得授权）。
若日后取得授权，改这一个字段即可，不必动数据。

无学生数据，故不进 `services/purge_service._STUDENT_TABLES`。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "pep1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "b3e9d1f5a7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS textbook_sentences (
            id             varchar(100) PRIMARY KEY,
            textbook_id    varchar(50)  NOT NULL
                            REFERENCES textbooks(id) ON DELETE CASCADE,
            page_number    integer,
            -- 版面位置：OCR 拼句的来源行数与最低置信度。留存是为了**可审计** ——
            -- 判断一句是不是被多栏拼坏的依据（见 scripts/ocr_pep_pages.py），
            -- 不留就无法复核门禁为什么放行/拒收。
            n_boxes        integer,
            min_score      real,
            sentence_index integer      NOT NULL,
            english_text   text         NOT NULL,
            chinese_text   text,
            -- 溯源：'PEP_OCR_RAPIDOCR' / 'FREEPEP'。
            source         varchar(64)  NOT NULL DEFAULT 'PEP_OCR_RAPIDOCR',
            license_status varchar(32)  NOT NULL DEFAULT 'unlicensed'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_textbook_sentences_textbook "
        "ON textbook_sentences (textbook_id, sentence_index)"
    )
    # 取句只按 (textbook_id, page) 走；english_text 建 trigram 意义不大
    # （词→句是经关联表走的），故不建。
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS textbook_sentence_occurrences (
            id                 varchar(100) PRIMARY KEY,
            sentence_id        varchar(100) NOT NULL
                               REFERENCES textbook_sentences(id) ON DELETE CASCADE,
            vocabulary_item_id varchar(100) NOT NULL
                               REFERENCES vocabulary_items(id) ON DELETE CASCADE,
            occurrence_index   integer      NOT NULL,
            token_start        integer,
            token_end          integer,
            created_at         timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_textbook_sentence_occurrence "
        "ON textbook_sentence_occurrences "
        "(sentence_id, vocabulary_item_id, occurrence_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_textbook_sentence_occ_vocab "
        "ON textbook_sentence_occurrences (vocabulary_item_id)"
    )
    # 英语教材入库，统一规范成 'english'：books/textbooks 这条链上
    # subject 历史上出现过 '英语'/'math'/'数学' 混写（296800f14b43 处理过一次），
    # 这里用 CHECK 之外的应用层枚举兜住，取句侧按 textbooks.subject 过滤。
    op.execute(
        """
        COMMENT ON TABLE textbook_sentences IS
            '人教社教材真实语境句（OCR 自位图页图）。Context Priority tier 1/2 的数据源。'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN textbook_sentences.license_status IS
            'unlicensed=未取得版权授权（当前值）。按整本教材下架时 DELETE FROM textbook_sentences WHERE textbook_id = 该书 id'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS textbook_sentence_occurrences")
    op.execute("DROP TABLE IF EXISTS textbook_sentences")
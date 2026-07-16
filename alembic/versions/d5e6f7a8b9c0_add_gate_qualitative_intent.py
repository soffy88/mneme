"""add gate.qualitative_intent (M1：意图与判据分表)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-16

R2 §2.1 M1 修复：把"该 KC 用定性门"的**意图**（教学设计决定）从 rubric 表（**判据**内容）
里剥离。此前 resolve_gate_type 用 rubric 存在性判 gate_type，导致删 rubric 同时撤销意图、
V12 逻辑不可测、build_path 与 resolve 在删 rubric 时判定不一致。

R2 §5 定稿两层解析：
  1) gate.qualitative_intent 有记录 → qualitative
  2) 默认                          → quantitative
rubric 表自此**只供判据**，不再承担门控意图。含 student_id 的表不受影响——本表按 kc_id，
无 PII，不入 purge。白名单层（12 类非数学科目）W2 并入本表来源。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qualitative_intent",
        sa.Column("kc_id", sa.String(100), primary_key=True),
        sa.Column(
            "reason", sa.Text, nullable=False
        ),  # 为何该 KC 走定性门（教学设计理由）
        sa.Column("author", sa.String(50), nullable=False),  # 'handwritten' | 人工署名
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="gate",
    )

    # 种子：ku004（函数的概念与表示）走定性门——DoD 定性桩。判据(rubric)已由 c4d5 播种。
    intent_tbl = sa.table(
        "qualitative_intent",
        sa.column("kc_id", sa.String),
        sa.column("reason", sa.Text),
        sa.column("author", sa.String),
        schema="gate",
    )
    op.bulk_insert(
        intent_tbl,
        [
            {
                "kc_id": "renjiao-math-g10-a-ku004",
                "reason": "函数的概念属概念性理解，须自我解释 + rubric 定性评判，非确定性判分",
                "author": "handwritten",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("qualitative_intent", schema="gate")

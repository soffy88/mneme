"""add gate schema (Phase1 门控内核持久化)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-15

Phase 1 门控内核（SPEC-002 §6.2 + 决策 D1）的持久化层。纯新增独立 schema `gate`，
不动 mneme 既有表。四张表：
  - gate.rubric            : 定性评分维度（D1）。**同时是 qualitative 注册表**——
                            某 KC 在此有行 ⟺ gate_type=qualitative（决策 D2.2 净规则）。
  - gate.pending_question  : 待答题；expected 只存这里，永不回传 agent。
  - gate.qualitative_mastery: concept/design 类 KC 的过门状态（唯一写入 = ReportResult+guard）。
  - gate.evidence          : llm_verified 裁决证据（防篡改审计）。

唯一写入者 = mneme 侧 mcp 工具面（gate_store）。student_id 用真实 UUID（与 kc_mastery/users 对齐），
不含匿名化前的 PII 泄给 agent —— agent 只经 MCP 工具触达，无 DB 连接。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS gate")

    # gate.rubric（D1）—— 定性评分维度 + qualitative 注册表
    op.create_table(
        "rubric",
        sa.Column("kc_id", sa.String(100), primary_key=True),
        # [{name, criterion, weight}]，与 SPEC §2 Rubric schema 对齐
        sa.Column("dimensions", postgresql.JSONB, nullable=False),
        sa.Column("author", sa.String(50), nullable=False),  # 'handwritten' | 人工署名
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="gate",
    )

    # gate.pending_question —— expected 只存这里，永不出 mneme 侧
    op.create_table(
        "pending_question",
        sa.Column("question_id", sa.String(64), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kc_id", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("expected", sa.Text, nullable=True),  # 定性题(open)无期望答案 → NULL
        sa.Column(
            "qtype", sa.String(16), nullable=False
        ),  # choice|short|fill|solve|open
        sa.Column(
            "posed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="gate",
    )
    op.create_index(
        "ix_gate_pending_student", "pending_question", ["student_id"], schema="gate"
    )

    # gate.qualitative_mastery —— concept/design 过门状态（唯一写入 = ReportResult+guard）
    op.create_table(
        "qualitative_mastery",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kc_id", sa.String(100), primary_key=True),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("evidence_ref", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="gate",
    )

    # gate.evidence —— llm_verified 裁决证据（防篡改审计）
    op.create_table(
        "evidence",
        sa.Column("evidence_ref", sa.String(64), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kc_id", sa.String(100), nullable=False),
        sa.Column("verdict", postgresql.JSONB, nullable=False),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="gate",
    )

    # D1.2 首个手写 rubric：ku004 函数的概念与表示（DoD 定性桩）
    # 用 bulk_insert 传 Python 对象（JSONB 自动序列化），避免 JSON 里的冒号被
    # SQLAlchemy 当成 :bind 参数（op.execute 会把裸字符串包进 text()）。
    rubric_tbl = sa.table(
        "rubric",
        sa.column("kc_id", sa.String),
        sa.column("dimensions", postgresql.JSONB),
        sa.column("author", sa.String),
        schema="gate",
    )
    op.bulk_insert(
        rubric_tbl,
        [
            {
                "kc_id": "renjiao-math-g10-a-ku004",
                "dimensions": [
                    {
                        "name": "对应关系本质",
                        "weight": 0.35,
                        "criterion": "能说明函数是两个非空数集间『每个 x 唯一对应一个 y』的对应关系，而非仅一个公式或图象",
                    },
                    {
                        "name": "三要素完整",
                        "weight": 0.25,
                        "criterion": "指出定义域、对应法则、值域三要素，并说明定义域与对应法则共同决定值域",
                    },
                    {
                        "name": "表示法辨识",
                        "weight": 0.20,
                        "criterion": "能区分解析法/列表法/图象法，并意识到同一函数可有多种表示",
                    },
                    {
                        "name": "反例判别",
                        "weight": 0.20,
                        "criterion": "能用『一对多不构成函数』判断给定对应是否为函数（给反例即算达标）",
                    },
                ],
                "author": "handwritten",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("evidence", schema="gate")
    op.drop_table("qualitative_mastery", schema="gate")
    op.drop_index("ix_gate_pending_student", "pending_question", schema="gate")
    op.drop_table("pending_question", schema="gate")
    op.drop_table("rubric", schema="gate")
    op.execute("DROP SCHEMA IF EXISTS gate")

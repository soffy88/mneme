"""drop_orphan_province_and_dead_tables

Revision ID: 346cdca5680a
Revises: 737a1fcd01b1
Create Date: 2026-07-09 08:14:25.074562

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "346cdca5680a"
down_revision: Union[str, Sequence[str], None] = "737a1fcd01b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# X.4 项目体检审计：users.province 跟此前删掉的 users.textbook_id 是一模一样的
# 孤儿列模式（157个用户全是默认值，零代码读写）。exams/daily_reports/
# learning_patterns 三张表建表至今从未被写入过（只有 purge_service.py 的
# GDPR 级联删除代码碰过，那部分本次改用 IF EXISTS 兜底，不因表消失而报错）——
# 分别被 users.exam_date（更轻量）、daily_plan_service（动态生成不落库）、
# get_patterns 端点（现场计算不落库）取代。


def upgrade() -> None:
    op.drop_column("users", "province")

    # papers.exam_id 本身也是零引用孤儿列（FK 指向即将删除的 exams 表），
    # 必须先删列（连带其 FK 约束）才能删 exams 表本身。
    op.drop_column("papers", "exam_id")

    op.drop_table("exams")
    op.drop_table("daily_reports")
    op.drop_table("learning_patterns")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("province", sa.String(length=10), server_default="广东"),
    )

    op.create_table(
        "exams",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.Column("exam_name", sa.String(length=100)),
        sa.Column("exam_date", sa.Date()),
        sa.Column("subject", sa.String(length=20), server_default="math"),
        sa.Column("total_score", sa.Integer()),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "daily_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.Column("date", sa.Date()),
        sa.Column("report_text", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_status", sa.String(length=20)),
        sa.UniqueConstraint("student_id", "date"),
    )

    op.create_table(
        "learning_patterns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")
        ),
        sa.Column("pattern_type", sa.String(length=50)),
        sa.Column("description", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("suggestion", sa.Text()),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("user_marked_useful", sa.Boolean()),
    )

    op.add_column(
        "papers",
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("exams.id")),
    )

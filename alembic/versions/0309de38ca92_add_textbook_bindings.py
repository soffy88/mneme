"""add_textbook_bindings

Revision ID: 0309de38ca92
Revises: b47f12cef853
Create Date: 2026-07-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0309de38ca92"
down_revision: Union[str, Sequence[str], None] = "b47f12cef853"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # N.4 用户教材绑定：加 textbook_bindings（JSONB，{subject: textbook_id}，
    # 同 daily_plan_prefs/accessibility_prefs 写法）。
    op.add_column(
        "users",
        sa.Column(
            "textbook_bindings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    # 同时清理 N.1(4ebc8f4ef067) 加的孤儿列 textbook_id：从未接入 ORM/任何代码
    # 读写过（单列也不够用——学生数学/物理/语文可能各用不同教材），改用上面的
    # JSONB 映射替代，不留两个教材相关字段并存造成困惑。
    op.drop_constraint("fk_users_textbook", "users", type_="foreignkey")
    op.drop_column("users", "textbook_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "users",
        sa.Column("textbook_id", sa.String(length=50), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_textbook", "users", "textbooks", ["textbook_id"], ["id"]
    )
    op.drop_column("users", "textbook_bindings")

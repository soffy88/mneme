"""add_email_registration

Revision ID: 2d9a0d6e3a53
Revises: 346cdca5680a
Create Date: 2026-07-09 11:47:28.650690

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d9a0d6e3a53"
down_revision: Union[str, Sequence[str], None] = "346cdca5680a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 邮箱注册：email 作为新注册/登录主标识（唯一、可空——157个老用户是手机号注册无
    # email）。phone 放松为可空（新邮箱用户没有手机号）。guardian_email 供<14邮箱注册
    # 的监护同意留联系方式，guardian_phone 同步放松可空。全部向后兼容，不破坏老数据。
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.alter_column("users", "phone", existing_type=sa.String(length=11), nullable=True)

    op.add_column(
        "guardian_consents",
        sa.Column("guardian_email", sa.String(length=254), nullable=True),
    )
    op.alter_column(
        "guardian_consents",
        "guardian_phone",
        existing_type=sa.String(length=11),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "guardian_consents",
        "guardian_phone",
        existing_type=sa.String(length=11),
        nullable=False,
    )
    op.drop_column("guardian_consents", "guardian_email")

    op.alter_column(
        "users", "phone", existing_type=sa.String(length=11), nullable=False
    )
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")

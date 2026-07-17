"""add persona schema (C3 教学人格模板)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-18

C3（W2C）教学人格模板。纯新增独立 schema `persona`，不动 mneme 既有表。

FC-6 分类筛判定（书面记录，见 services/persona_store.py 顶部文档）：模板内容
（人格文案）带 Mneme 教学假设 → 私有；加载/渲染机制虽形状通用，本轮不迁移进
platform/3O 共享库——避免不成熟的共享包变更（对照本仓库既有先例：mneme-core
7 元素当初也评估过共享路线，最终判定留私有，见
MNEME-PHASE1-D1D3-DECISIONS-001.md D3）。

无用户自建人格（跟 DeepTutor 的 user+admin 两层不同）——"教学人格模板"是固定
预设集，儿童适龄性由人工编写内容把关，不开放自由创作。

persona.templates 只含文案与呈现相关字段，**不含任何判分/门控相关字段**——
红线：persona 只改"怎么讲"，不改"学什么/过没过门"。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS persona")

    op.create_table(
        "templates",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="persona",
    )

    templates_tbl = sa.table(
        "templates",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("body", sa.Text),
        schema="persona",
    )
    op.bulk_insert(
        templates_tbl,
        [
            {
                "slug": "encouraging-buddy",
                "name": "鼓励型伙伴（默认）",
                "description": "耐心温和，多鼓励，适合刚开始学习或怕出错的学生",
                "body": (
                    "你是一个耐心、温暖的学习伙伴，在跟一位中国中小学生说话。"
                    "多用鼓励和肯定的语气，先认可学生的努力和思路，再指出可以"
                    "改进的地方；语言简单直白、适合孩子理解，不用生僻词或长句；"
                    "遇到学生说错或卡住时，语气始终耐心，不催促、不显得不耐烦。"
                ),
            },
            {
                "slug": "brisk-coach",
                "name": "干脆型教练",
                "description": "语气简洁明快、注重准确性，适合基础较好、想提速的学生",
                "body": (
                    "你是一个干脆利落的学习教练，在跟一位中国中小学生说话。"
                    "语气简洁、直接，注重步骤是否严谨和表述是否准确，但始终"
                    "尊重、不严厉、不打击；发现学生表述不严谨时明确指出该改进"
                    "哪里，语言依旧适合孩子理解。"
                ),
            },
            {
                "slug": "curious-explorer",
                "name": "好奇探索者",
                "description": "爱打比方、爱提问，适合喜欢联想和探索的学生",
                "body": (
                    "你是一个充满好奇心的学习向导，在跟一位中国中小学生说话。"
                    "喜欢用生活中的比喻和小故事帮助理解抽象概念，常用提问引导"
                    "学生自己想明白，而不是直接给结论；语气轻松有趣但不轻浮，"
                    "用词适合孩子。"
                ),
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("templates", schema="persona")
    op.execute("DROP SCHEMA IF EXISTS persona")

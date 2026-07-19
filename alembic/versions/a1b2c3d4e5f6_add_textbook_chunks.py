"""add textbook_chunks table for RAG

Revision ID: a1b2c3d4e5f6
Revises: f7e4a5b6c9d0
Create Date: 2026-07-14

textbook_chunks：教材分块存储 + 向量嵌入（float8[]）。
使用 PostgreSQL 原生 ARRAY(FLOAT8) 存向量，应用层 numpy cosine 相似度检索。
不依赖 pgvector 扩展，与现有 pg16 栈完全兼容。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'a1b2c3d4e5f6'
down_revision = '2d9a0d6e3a53'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'textbook_chunks',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('file_id', sa.String(50), sa.ForeignKey('textbook_files.id', ondelete='CASCADE'), nullable=False),
        # 定位信息
        sa.Column('page_number', sa.Integer, nullable=True),        # PDF 页码（1-indexed）
        sa.Column('section_title', sa.String(500), nullable=True),  # 章节标题（若可提取）
        sa.Column('chunk_index', sa.Integer, nullable=False),        # 文件内顺序
        # 内容
        sa.Column('content', sa.Text, nullable=False),              # 原始文本
        sa.Column('content_length', sa.Integer, nullable=False),    # 字符数
        # 向量嵌入（float8[]，应用层 cosine 检索）
        sa.Column('embedding', postgresql.ARRAY(sa.Float(precision=8)), nullable=True),
        sa.Column('embedding_model', sa.String(100), nullable=True),  # 记录用哪个模型生成的
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True),
        # 时间戳
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    # 按文件查所有 chunks（构建索引时扫）
    op.create_index('ix_tc_file_id', 'textbook_chunks', ['file_id'])
    # 按文件 + chunk 顺序（渲染引用位置时按顺序取）
    op.create_index('ix_tc_file_chunk', 'textbook_chunks', ['file_id', 'chunk_index'])
    # 筛选已嵌入的 chunks
    op.create_index('ix_tc_embedded', 'textbook_chunks', ['file_id', 'embedded_at'],
                    postgresql_where=sa.text('embedded_at IS NOT NULL'))

    # textbook_files 加索引状态字段
    op.add_column('textbook_files',
        sa.Column('index_status', sa.String(20), server_default='pending', nullable=False))
    # pending | indexing | ready | error
    op.add_column('textbook_files',
        sa.Column('index_error', sa.Text, nullable=True))
    op.add_column('textbook_files',
        sa.Column('chunk_count', sa.Integer, nullable=True))
    op.add_column('textbook_files',
        sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('textbook_files', 'indexed_at')
    op.drop_column('textbook_files', 'chunk_count')
    op.drop_column('textbook_files', 'index_error')
    op.drop_column('textbook_files', 'index_status')
    op.drop_table('textbook_chunks')

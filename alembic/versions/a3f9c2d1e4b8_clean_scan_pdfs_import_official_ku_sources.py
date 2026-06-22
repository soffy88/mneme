"""clean_scan_pdfs_import_official_ku_sources

清理本地扫描版 textbook_files（118 条 s3 批 + 5 条 platform 占位），
导入 curriculum_standards/ 里 7 本官方文字版教材作为 KU 对应 PDF。

Revision ID: a3f9c2d1e4b8
Revises: 51e587e6c96c
Create Date: 2026-06-22
"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa

revision: str = 'a3f9c2d1e4b8'
down_revision: Union[str, Sequence[str], None] = '51e587e6c96c'
branch_labels = None
depends_on = None

# 7 本官方文字版 PDF（来自 curriculum_standards/，国家中小学智慧教育平台下载）
_OFFICIAL_PDFS = [
    {
        'textbook_id': 'RENJIAO-G7-MATH-X',
        'filename':    'G7_14_数学七年级下册.pdf',
        'file_size':   28191405,
    },
    {
        'textbook_id': 'RENJIAO-G8-MATH-X',
        'filename':    'G8_16_数学八年级下册.pdf',
        'file_size':   18713833,
    },
    {
        'textbook_id': 'RENJIAO-G9-MATH-S',
        'filename':    'G9_17_数学九年级上册.pdf',
        'file_size':   8987068,
    },
    {
        'textbook_id': 'renjiao-math-g10-a',
        'filename':    'G10_19_高中数学必修一（A版）.pdf',
        'file_size':   22544333,
    },
    {
        'textbook_id': 'RENJIAO-G11-MATH-A-SBX1',
        'filename':    'G11_21_高中数学选择性必修一（A版）.pdf',
        'file_size':   21351434,
    },
    {
        'textbook_id': 'RENJIAO-G11-MATH-A-SBX2',
        'filename':    'G11_22_高中数学选择性必修二（A版）.pdf',
        'file_size':   16591388,
    },
    {
        'textbook_id': 'RENJIAO-G12-MATH-A-SBX3',
        'filename':    'G12_23_高中数学选择性必修三（A版）.pdf',
        'file_size':   21132296,
    },
]


def upgrade() -> None:
    # ── 1. 清理 platform/ 占位记录的关联数据（测试数据）──────────────────────
    # reading_notes 有 fk_rn_highlight -> highlights，必须先删 notes 再删 highlights
    op.execute("""
        DELETE FROM reading_notes
        WHERE file_id IN (
            SELECT id FROM textbook_files WHERE storage_path LIKE 'platform/%'
        )
        OR highlight_id IN (
            SELECT h.id FROM highlights h
            JOIN textbook_files f ON h.file_id = f.id
            WHERE f.storage_path LIKE 'platform/%'
        )
    """)
    op.execute("""
        DELETE FROM highlights
        WHERE file_id IN (
            SELECT id FROM textbook_files WHERE storage_path LIKE 'platform/%'
        )
    """)

    # ── 2. 删除 5 条 platform/ 占位 textbook_files ────────────────────────────
    op.execute("DELETE FROM textbook_files WHERE storage_path LIKE 'platform/%'")

    # ── 3. 删除 118 条本地扫描版 s3 textbook_files（保留 BX2）────────────────
    op.execute("""
        DELETE FROM textbook_files
        WHERE storage_path LIKE 's3://%'
          AND textbook_id != 'RENJIAO-G10-MATH-BX2'
    """)

    # ── 4. 导入 7 本官方文字版 PDF（curriculum_standards/）────────────────────
    for row in _OFFICIAL_PDFS:
        fid = str(uuid.uuid4())
        storage = f"curriculum_standards/{row['filename']}"
        op.execute(sa.text("""
            INSERT INTO textbook_files
              (id, textbook_id, filename, file_type, storage_path,
               file_size, has_text_layer, uploaded_at)
            VALUES
              (:id, :textbook_id, :filename, 'pdf', :storage_path,
               :file_size, true, now())
            ON CONFLICT DO NOTHING
        """).bindparams(
            id=fid,
            textbook_id=row['textbook_id'],
            filename=row['filename'],
            storage_path=storage,
            file_size=row['file_size'],
        ))


def downgrade() -> None:
    # 删除导入的 7 条官方 PDF 记录
    for row in _OFFICIAL_PDFS:
        op.execute(sa.text(
            "DELETE FROM textbook_files WHERE textbook_id=:tid AND storage_path LIKE 'curriculum_standards/%'"
        ).bindparams(tid=row['textbook_id']))

    # 注意：downgrade 不恢复已删除的 118 条扫描版和 5 条 platform 记录
    # （恢复需要重新运行 import_textbooks.py，这里只回滚 upgrade 的导入部分）

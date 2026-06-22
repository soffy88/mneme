"""import_g1_g9_official_ku_pdfs

补充导入 G1-G9 共 15 本 KU 对应的官方文字版 PDF（curriculum_standards/）。
前一个 migration 清理 s3 扫描版时也清掉了这些原本已挂 PDF 的教材，这里补回来。

Revision ID: b1e7d4f2c9a5
Revises: a3f9c2d1e4b8
Create Date: 2026-06-22
"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa

revision: str = 'b1e7d4f2c9a5'
down_revision: Union[str, Sequence[str], None] = 'a3f9c2d1e4b8'
branch_labels = None
depends_on = None

_PDFS = [
    ('RENJIAO-G1-MATH-S', 'G1_01_数学一年级上册.pdf',  53929783),
    ('RENJIAO-G1-MATH-X', 'G1_02_数学一年级下册.pdf',  17807766),
    ('RENJIAO-G2-MATH-S', 'G2_03_数学二年级上册.pdf',  11546160),
    ('RENJIAO-G2-MATH-X', 'G2_04_数学二年级下册.pdf',  14496305),
    ('RENJIAO-G3-MATH-S', 'G3_05_数学三年级上册.pdf',  31564754),
    ('RENJIAO-G3-MATH-X', 'G3_06_数学三年级下册.pdf',  11677562),
    ('RENJIAO-G4-MATH-S', 'G4_07_数学四年级上册.pdf',  21482152),
    ('RENJIAO-G4-MATH-X', 'G4_08_数学四年级下册.pdf',  12001311),
    ('RENJIAO-G5-MATH-S', 'G5_09_数学五年级上册.pdf',  32386256),
    ('RENJIAO-G5-MATH-X', 'G5_10_数学五年级下册.pdf',   9948030),
    ('RENJIAO-G6-MATH-S', 'G6_11_数学六年级上册.pdf',  15659729),
    ('RENJIAO-G6-MATH-X', 'G6_12_数学六年级下册.pdf',  11281480),
    ('RENJIAO-G7-MATH-S', 'G7_13_数学七年级上册.pdf',  12225888),
    ('RENJIAO-G8-MATH-S', 'G8_15_数学八年级上册.pdf',   9447271),
    ('RENJIAO-G9-MATH-X', 'G9_18_数学九年级下册.pdf',  10269933),
]


def upgrade() -> None:
    for textbook_id, filename, file_size in _PDFS:
        op.execute(sa.text("""
            INSERT INTO textbook_files
              (id, textbook_id, filename, file_type, storage_path,
               file_size, has_text_layer, uploaded_at)
            VALUES
              (:id, :textbook_id, :filename, 'pdf',
               :storage_path, :file_size, true, now())
            ON CONFLICT DO NOTHING
        """).bindparams(
            id=str(uuid.uuid4()),
            textbook_id=textbook_id,
            filename=filename,
            storage_path=f'curriculum_standards/{filename}',
            file_size=file_size,
        ))


def downgrade() -> None:
    for textbook_id, _, _ in _PDFS:
        op.execute(sa.text(
            "DELETE FROM textbook_files "
            "WHERE textbook_id=:tid AND storage_path LIKE 'curriculum_standards/%'"
        ).bindparams(tid=textbook_id))

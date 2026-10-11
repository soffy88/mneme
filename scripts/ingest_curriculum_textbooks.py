#!/usr/bin/env python3
"""Ingest curriculum textbook PDFs into the Knowledge Hub (textbook_files + textbook_chunks).

Runs inside the api container (needs pymupdf4llm + the embedding provider):

    docker exec mneme-api-1 python scripts/ingest_curriculum_textbooks.py --subjects physics english
    docker exec mneme-api-1 python scripts/ingest_curriculum_textbooks.py --dry-run

Data only: inserts new textbook_files rows and their chunks via the existing
`services.textbook_qa_service.index_textbook_file` pipeline (same chunker and
embedding model as W3 A2, so vectors share one space). Never touches a file row
it did not create: a textbook that already has a `ready` file with the same
filename is skipped; a previous failed/pending row created by this script
(storage_path under curriculum_standards/) is re-indexed in place.

The mapping below binds PDFs in curriculum_standards/ to existing `textbooks`
rows (it does not create textbooks).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("MNEME_ROOT") or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

CS = "curriculum_standards"
_M22 = "（根据2022年版课程标准修订）义务教育教科书"

# (subject, textbook_id, filename under curriculum_standards/)
MAPPING: list[tuple[str, str, str]] = [
    # physics — 人教版
    ("physics", "RENJIAO-G8-PHYSICS-S", f"M_物理_{_M22}·物理八年级上册.pdf"),
    ("physics", "RENJIAO-G8-PHYSICS-X", f"M_物理_{_M22}·物理八年级下册.pdf"),
    ("physics", "RENJIAO-G9-PHYSICS-QYC", f"M_物理_{_M22}·物理九年级全一册.pdf"),
    ("physics", "RENJIAO-G10-PHYSICS-BX1", "H_物理_普通高中教科书·物理必修第一册.pdf"),
    ("physics", "RENJIAO-G10-PHYSICS-BX2", "H_物理_普通高中教科书·物理必修第二册.pdf"),
    ("physics", "RENJIAO-G11-PHYSICS-BX3", "H_物理_普通高中教科书·物理必修第三册.pdf"),
    ("physics", "RENJIAO-G11-PHYSICS-SBX1", "H_物理_普通高中教科书·物理选择性必修第一册.pdf"),
    ("physics", "RENJIAO-G11-PHYSICS-SBX2", "H_物理_普通高中教科书·物理选择性必修第二册.pdf"),
    ("physics", "RENJIAO-G12-PHYSICS-SBX3", "H_物理_普通高中教科书·物理选择性必修第三册.pdf"),
    # english — 人教版 PEP
    ("english", "pep-en-g7b", f"M_英语_{_M22}·英语七年级下册.pdf"),
    ("english", "pep-en-g8a", f"M_英语_{_M22}·英语八年级上册.pdf"),
    ("english", "pep-en-g8b", f"M_英语_{_M22}·英语八年级下册.pdf"),
    ("english", "pep-en-g9all", "M_英语_义务教育教科书·英语九年级全一册.pdf"),
    ("english", "pep-en-h1", "H_英语_普通高中教科书·英语必修第一册.pdf"),
    ("english", "pep-en-h2", "H_英语_普通高中教科书·英语必修第二册.pdf"),
    ("english", "pep-en-h3", "H_英语_普通高中教科书·英语必修第三册.pdf"),
    ("english", "pep-en-hs1", "H_英语_普通高中教科书·英语选择性必修第一册.pdf"),
    ("english", "pep-en-hs2", "H_英语_普通高中教科书·英语选择性必修第二册.pdf"),
    ("english", "pep-en-hs3", "H_英语_普通高中教科书·英语选择性必修第三册.pdf"),
    ("english", "pep-en-hs4", "H_英语_普通高中教科书·英语选择性必修第四册.pdf"),
    # chinese — 统编版
    ("chinese", "TONGBIAN-G7-CHINESE-S", f"M_语文_{_M22}·语文七年级上册.pdf"),
    ("chinese", "TONGBIAN-G7-CHINESE-X", f"M_语文_{_M22}·语文七年级下册.pdf"),
    ("chinese", "TONGBIAN-G8-CHINESE-S", f"M_语文_{_M22}·语文八年级上册.pdf"),
    ("chinese", "TONGBIAN-G8-CHINESE-X", f"M_语文_{_M22}·语文八年级下册.pdf"),
    ("chinese", "TONGBIAN-G9-CHINESE-S", "M_语文_义务教育教科书·语文九年级上册.pdf"),
    ("chinese", "TONGBIAN-G9-CHINESE-X", "M_语文_义务教育教科书·语文九年级下册.pdf"),
    ("chinese", "TONGBIAN-G10-CHINESE-BXS", "H_语文_普通高中教科书·语文必修上册.pdf"),
    ("chinese", "TONGBIAN-G10-CHINESE-BXX", "H_语文_普通高中教科书·语文必修下册.pdf"),
    ("chinese", "TONGBIAN-G11-CHINESE-SBXS", "H_语文_普通高中教科书·语文选择性必修上册.pdf"),
    ("chinese", "TONGBIAN-G11-CHINESE-SBXM", "H_语文_普通高中教科书·语文选择性必修中册.pdf"),
    ("chinese", "TONGBIAN-G12-CHINESE-SBXX", "H_语文_普通高中教科书·语文选择性必修下册.pdf"),
    # history — 统编版
    ("history", "TONGBIAN-G7-HISTORY-S", f"M_历史_{_M22}·中国历史七年级上册.pdf"),
]


async def _ingest_one(textbook_id: str, filename: str, *, dry_run: bool) -> str:
    from sqlalchemy import text as sa_text

    from obase.db import SessionLocal
    from services.textbook_qa_service import index_textbook_file

    path = ROOT / CS / filename
    if not path.is_file():
        return "missing_pdf"
    storage_path = f"{CS}/{filename}"
    async with SessionLocal() as db:
        tb = (
            await db.execute(
                sa_text("SELECT 1 FROM textbooks WHERE id=:id"), {"id": textbook_id}
            )
        ).fetchone()
        if tb is None:
            return "missing_textbook_row"
        existing = (
            await db.execute(
                sa_text(
                    "SELECT id, index_status, storage_path FROM textbook_files "
                    "WHERE textbook_id=:tb AND filename=:fn ORDER BY uploaded_at"
                ),
                {"tb": textbook_id, "fn": filename},
            )
        ).fetchall()
        if any(r.index_status == "ready" for r in existing):
            return "skip_ready"
        if dry_run:
            return "would_ingest"
        reusable = [r for r in existing if r.storage_path == storage_path]
        if reusable:
            file_id = reusable[0].id
        else:
            file_id = str(uuid.uuid4())
            await db.execute(
                sa_text(
                    "INSERT INTO textbook_files (id, textbook_id, filename, file_type,"
                    " storage_path, file_size, has_text_layer, index_status)"
                    " VALUES (:id, :tb, :fn, 'pdf', :sp, :sz, NULL, 'pending')"
                ),
                {
                    "id": file_id,
                    "tb": textbook_id,
                    "fn": filename,
                    "sp": storage_path,
                    "sz": path.stat().st_size,
                },
            )
            await db.commit()
        res = await index_textbook_file(
            db, file_id=file_id, file_data=path.read_bytes(), file_type="pdf"
        )
    if res.get("status") != "ready":
        return f"error:{res.get('error', '')[:120]}"
    return f"ready chunks={res['chunk_count']} embedded={res['embedded_count']}"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subjects", nargs="*", help="physics english chinese history")
    ap.add_argument("--textbook", action="append", help="only these textbook ids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = [
        m
        for m in MAPPING
        if (not args.subjects or m[0] in args.subjects)
        and (not args.textbook or m[1] in args.textbook)
    ]
    for subject, tb_id, fn in rows:
        t0 = time.time()
        status = await _ingest_one(tb_id, fn, dry_run=args.dry_run)
        print(f"{subject}\t{tb_id}\t{status}\t{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

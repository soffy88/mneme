#!/usr/bin/env python3
"""
批量导入教材 PDF 到 PostgreSQL + MinIO。
运行方式（在 api 容器内，books 目录需挂载到 /books）：
  docker compose exec -v ~/books:/books api python scripts/import_textbooks.py
幂等：同 textbook_id + filename 已存在则跳过。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# ── 依赖检查 ─────────────────────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("缺少 PyMuPDF：pip install pymupdf")

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    sys.exit("缺少 boto3：pip install boto3")

try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg：pip install asyncpg")

# ── 配置 ─────────────────────────────────────────────────────────────────────

PLAN_FILE = Path(__file__).parent / "textbook_import_plan.json"
MINIO_BUCKET = "textbooks"
TEXT_MIN_CHARS = 50  # 前3页字符数超过此值视为有文字层


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _pg_dsn() -> str:
    raw = _env("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/mneme")
    # 去掉 SQLAlchemy driver 前缀
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def _minio_client():
    endpoint = _env("MINIO_ENDPOINT", "minio:9000")
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_env("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=_env("MINIO_SECRET_KEY", "minioadmin"),
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


# ── 文字层检测 ────────────────────────────────────────────────────────────────

def detect_text_layer(pdf_path: str) -> bool:
    """提取前 3 页文本，总字符数 > TEXT_MIN_CHARS 视为有文字层。"""
    try:
        doc = fitz.open(pdf_path)
        total = 0
        for i in range(min(3, len(doc))):
            total += len(doc[i].get_text().strip())
            if total > TEXT_MIN_CHARS:
                doc.close()
                return True
        doc.close()
        return False
    except Exception as e:
        print(f"    ⚠ 文字层检测失败: {e}")
        return False


# ── MinIO 上传 ────────────────────────────────────────────────────────────────

def ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket", "403"):
            s3.create_bucket(Bucket=bucket)
            print(f"  ✔ 创建 bucket: {bucket}")
        else:
            raise


def upload_pdf(s3, bucket: str, object_key: str, file_path: str, file_size: int) -> None:
    MB = 1024 * 1024
    if file_size > 100 * MB:
        mpu = s3.create_multipart_upload(Bucket=bucket, Key=object_key, ContentType="application/pdf")
        upload_id = mpu["UploadId"]
        part_size = 50 * MB
        parts = []
        try:
            with open(file_path, "rb") as f:
                part_num = 0
                uploaded = 0
                while True:
                    data = f.read(part_size)
                    if not data:
                        break
                    part_num += 1
                    resp = s3.upload_part(
                        Bucket=bucket, Key=object_key,
                        UploadId=upload_id, PartNumber=part_num, Body=data,
                    )
                    parts.append({"PartNumber": part_num, "ETag": resp["ETag"]})
                    uploaded += len(data)
                    pct = uploaded * 100 // file_size
                    print(f"\r    上传中 {pct:3d}%  ({uploaded/MB:.0f}/{file_size/MB:.0f} MB)", end="", flush=True)
            s3.complete_multipart_upload(
                Bucket=bucket, Key=object_key, UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            print()
        except Exception:
            s3.abort_multipart_upload(Bucket=bucket, Key=object_key, UploadId=upload_id)
            raise
    else:
        with open(file_path, "rb") as f:
            s3.put_object(Bucket=bucket, Key=object_key, Body=f, ContentType="application/pdf")


# ── DB 操作 ──────────────────────────────────────────────────────────────────

async def upsert_textbook(conn, entry: dict) -> None:
    await conn.execute("""
        INSERT INTO textbooks (id, subject, grade, edition, book_name)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (id) DO UPDATE
            SET subject   = EXCLUDED.subject,
                grade     = EXCLUDED.grade,
                edition   = EXCLUDED.edition,
                book_name = EXCLUDED.book_name
    """, entry["textbook_id"], entry["subject"], entry["grade"],
         entry["edition"], entry["book_name"])


async def file_already_imported(conn, textbook_id: str, filename: str) -> bool:
    row = await conn.fetchrow(
        "SELECT id FROM textbook_files WHERE textbook_id = $1 AND filename = $2 LIMIT 1",
        textbook_id, filename,
    )
    return row is not None


async def insert_textbook_file(conn, entry: dict, storage_path: str,
                                file_size: int, has_text_layer: bool) -> str:
    raw = f"{entry['textbook_id']}:{entry['filename']}"
    file_id = hashlib.sha1(raw.encode()).hexdigest()[:40]
    await conn.execute("""
        INSERT INTO textbook_files
            (id, textbook_id, owner_student_id, filename, file_type,
             storage_path, file_size, has_text_layer)
        VALUES ($1, $2, NULL, $3, 'pdf', $4, $5, $6)
        ON CONFLICT (id) DO UPDATE
            SET storage_path   = EXCLUDED.storage_path,
                file_size      = EXCLUDED.file_size,
                has_text_layer = EXCLUDED.has_text_layer
    """, file_id, entry["textbook_id"], entry["filename"],
         storage_path, file_size, has_text_layer)
    return file_id


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def run(plan_entries: list[dict], dry_run: bool) -> None:
    to_import = [e for e in plan_entries if e["action"] == "import"]
    total = len(to_import)
    print(f"计划导入 {total} 本教材（dry_run={dry_run}）\n")

    if dry_run:
        for i, e in enumerate(to_import, 1):
            print(f"[{i}/{total}] {e['book_name']}  ({e['file_size_mb']:.1f}MB)  id={e['textbook_id']}")
        return

    conn = await asyncpg.connect(_pg_dsn())
    s3 = _minio_client()
    ensure_bucket(s3, MINIO_BUCKET)

    results: dict[str, list] = {"ok": [], "skip": [], "fail": []}
    scan_only: list[str] = []

    t_start = time.time()

    for idx, entry in enumerate(to_import, 1):
        book_name = entry["book_name"]
        textbook_id = entry["textbook_id"]
        file_path = entry["file_path"]
        filename = entry["filename"]
        file_size = int(entry["file_size_mb"] * 1024 * 1024)

        label = f"[{idx}/{total}] {book_name} ({entry['file_size_mb']:.1f}MB)"
        print(label, end=" ", flush=True)

        if not Path(file_path).exists():
            # PDF在容器外，尝试挂载路径 /books/教材/filename
            alt = Path("/books/教材") / filename
            if alt.exists():
                file_path = str(alt)
                entry = {**entry, "file_path": file_path}
            else:
                print(f"❌ 文件不存在 (原路径: {file_path})")
                results["fail"].append({"id": textbook_id, "reason": "文件不存在"})
                continue

        try:
            # 幂等检查
            if await file_already_imported(conn, textbook_id, filename):
                print("⏭ 已导入")
                results["skip"].append(textbook_id)
                continue

            # 1. upsert textbooks
            await upsert_textbook(conn, entry)

            # 2. 文字层检测
            has_text = detect_text_layer(file_path)

            # 3. MinIO 上传
            object_key = f"{textbook_id}/{filename}"
            storage_path = f"s3://{MINIO_BUCKET}/{object_key}"
            upload_pdf(s3, MINIO_BUCKET, object_key, file_path, file_size)

            # 4. textbook_files 登记
            await insert_textbook_file(conn, entry, storage_path, file_size, has_text)

            tag = "✅" if has_text else "🖼 扫描版"
            print(tag)
            results["ok"].append(textbook_id)
            if not has_text:
                scan_only.append(book_name)

        except Exception as exc:
            print(f"❌ {exc}")
            results["fail"].append({"id": textbook_id, "reason": str(exc)})

    await conn.close()

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完成！耗时 {elapsed:.0f}s")
    print(f"  成功导入: {len(results['ok'])} 本")
    print(f"  已跳过:   {len(results['skip'])} 本（幂等）")
    print(f"  失败:     {len(results['fail'])} 本")

    if results["fail"]:
        print("\n失败列表：")
        for f in results["fail"]:
            print(f"  ❌ {f['id']}: {f['reason']}")

    print(f"\n扫描版（无文字层）共 {len(scan_only)} 本：")
    for name in scan_only:
        print(f"  🖼 {name}")

    if results["fail"]:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(PLAN_FILE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        sys.exit(f"找不到计划文件: {plan_path}")

    with open(plan_path, encoding="utf-8") as f:
        entries = json.load(f)

    asyncio.run(run(entries, args.dry_run))


if __name__ == "__main__":
    main()

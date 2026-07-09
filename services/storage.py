"""MinIO 文件存储工具 — 教材文件 upload/download/delete。"""

from __future__ import annotations

import io
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from obase.config import settings

TEXTBOOKS_BUCKET = "textbooks"
# curriculum_standards/ 文件直接从容器内文件系统读取（无需上传 MinIO）
_CURRICULUM_DIR = Path("/app/curriculum_standards")


def _client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=False,
    )


def ensure_bucket() -> None:
    c = _client()
    if not c.bucket_exists(TEXTBOOKS_BUCKET):
        c.make_bucket(TEXTBOOKS_BUCKET)


def upload_file(object_path: str, data: bytes, content_type: str) -> None:
    ensure_bucket()
    c = _client()
    c.put_object(
        TEXTBOOKS_BUCKET,
        object_path,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def download_file(object_path: str) -> bytes:
    # curriculum_standards/ 文件直接从本地文件系统读（不走 MinIO）
    if object_path.startswith("curriculum_standards/"):
        filename = object_path[len("curriculum_standards/") :]
        local = _CURRICULUM_DIR / filename
        if local.exists():
            return local.read_bytes()
        raise FileNotFoundError(f"Curriculum file not found on disk: {local}")
    c = _client()
    try:
        resp = c.get_object(TEXTBOOKS_BUCKET, object_path)
        return resp.read()
    except S3Error as e:
        raise FileNotFoundError(f"Object not found: {object_path}") from e


def content_type_for(file_type: str) -> str:
    return "application/epub+zip" if file_type == "epub" else "application/pdf"

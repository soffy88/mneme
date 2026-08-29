"""MinIO 文件存储工具 — 教材文件 + Immersive media upload/download/delete。"""

from __future__ import annotations

import io
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from obase.config import settings

TEXTBOOKS_BUCKET = "textbooks"
MEDIA_BUCKET = "immersive-media"
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


def ensure_media_bucket() -> None:
    c = _client()
    if not c.bucket_exists(MEDIA_BUCKET):
        c.make_bucket(MEDIA_BUCKET)


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


def upload_media_file(object_path: str, data: bytes, content_type: str) -> None:
    """Upload an immersive media object (key only; never store signed URLs)."""
    ensure_media_bucket()
    c = _client()
    c.put_object(
        MEDIA_BUCKET,
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


def download_media_file(object_path: str) -> bytes:
    c = _client()
    try:
        resp = c.get_object(MEDIA_BUCKET, object_path)
        return resp.read()
    except S3Error as e:
        raise FileNotFoundError(f"Media object not found: {object_path}") from e


def delete_file(object_path: str) -> None:
    """删除 MinIO blob。对象不存在时静默（幂等），其余错误由调用方决定是否吞掉。

    修复审计项"textbook_files 删除只删 DB 行、MinIO blob 残留"：物理删除教材
    文件时（purge_service 硬删、未来的删除端点）同步清掉存储层对象，不留孤儿 blob。
    """
    c = _client()
    try:
        c.remove_object(TEXTBOOKS_BUCKET, object_path)
    except S3Error as e:
        if e.code == "NoSuchKey":
            return
        raise


def delete_media_file(object_path: str) -> None:
    """Delete an immersive-media blob. Missing object is idempotent success."""
    c = _client()
    try:
        c.remove_object(MEDIA_BUCKET, object_path)
    except S3Error as e:
        if e.code == "NoSuchKey":
            return
        raise


def content_type_for(file_type: str) -> str:
    return "application/epub+zip" if file_type == "epub" else "application/pdf"


def content_type_for_media(extension: str) -> str:
    mapping = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
    }
    return mapping.get(extension.lower(), "application/octet-stream")


def presign_media_get_url(object_path: str, expires_seconds: int = 3600) -> str:
    """Return a short-lived signed GET URL. Never persist this as storage_ref."""

    from datetime import timedelta

    ensure_media_bucket()
    c = _client()
    return c.presigned_get_object(
        MEDIA_BUCKET,
        object_path,
        expires=timedelta(seconds=expires_seconds),
    )

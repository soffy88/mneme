"""教学交互页的前端静态依赖（自托管）。

three.js / MathJax / KaTeX / Tailwind Play 的固定版本副本放在
``services/assets/vendor/``，交互课模板只引用 ``/v1/edu-assets/...``，
不再依赖境外 CDN（jsdelivr / unpkg / cdnjs 在国内不稳定）。

只读、免登录（都是公开的开源库），白名单后缀，路径不得越出 vendor 目录，
长缓存（文件名含版本号）。各库 LICENSE 与文件同目录保存。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/v1/edu-assets", tags=["edu-assets"])

VENDOR_DIR = (Path(__file__).resolve().parent.parent / "assets" / "vendor").resolve()
_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
}
_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    # 交互课在 Studio 里以 sandbox iframe（opaque origin）加载，ES module 脚本走 CORS
    "Access-Control-Allow-Origin": "*",
    "X-Content-Type-Options": "nosniff",
}


def resolve_asset(path: str) -> Path | None:
    """把请求路径解析为 vendor 目录内的已存在文件；不合法返回 None。"""
    if not path or "\\" in path or path.startswith("/"):
        return None
    candidate = (VENDOR_DIR / path).resolve()
    if VENDOR_DIR not in candidate.parents:
        return None
    if candidate.suffix not in _CONTENT_TYPES or not candidate.is_file():
        return None
    return candidate


@router.get("/{path:path}")
async def edu_asset(path: str) -> FileResponse:
    file = resolve_asset(path)
    if file is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(file, media_type=_CONTENT_TYPES[file.suffix], headers=_HEADERS)

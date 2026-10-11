"""相关实验外链（WeduLab）：静态目录 + 确定性匹配，只读、免登录。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.related_labs import SOURCE_HOME, SOURCE_NAME, catalog, match_related_labs

router = APIRouter(prefix="/v1/related-labs", tags=["related-labs"])

Subject = Literal["math", "physics", "chemistry", "biology", "geography", "history"]
_CACHE = {"Cache-Control": "public, max-age=3600"}


def _source() -> dict[str, str]:
    return {"name": SOURCE_NAME, "home": SOURCE_HOME, "note": "外部站点，新窗口打开"}


@router.get("")
async def list_related_labs() -> JSONResponse:
    """全部外链实验（按学科分组由前端完成）。"""
    return JSONResponse({"source": _source(), "labs": catalog()}, headers=_CACHE)


@router.get("/match")
async def match_labs(
    q: str = Query("", max_length=500, description="知识点名 / 错因标签 / 题干摘要"),
    kc_id: str | None = Query(None, max_length=64),
    subject: Subject | None = None,
    limit: int = Query(3, ge=1, le=10),
) -> JSONResponse:
    labs = match_related_labs(q, kc_id=kc_id, subject=subject, limit=limit)
    return JSONResponse({"source": _source(), "labs": labs}, headers=_CACHE)

"""notebook_service —— 学习者笔记本（DeepTutor Notebook 对标）。

学习者把聊天回答、活书内容块、解题/可视化结果、研究报告或自由文本存进自己命名的
笔记本；每条记录保留 source_type + source_id + kc_id（已知时）。

权限口径：**owner-only**。现有授权模型（agent.user_grants）只是 admin 设的
per-student 工具白名单，不含"家长可读孩子笔记"这一授权，所以家长/他人一律不可读写
（笔记是孩子自己的整理，不是学习档案）。所有查询在 SQL 层强制 student_id 条件。

红线：笔记永不进掌握度/门控——本模块只读写 notebooks / notebook_records 两张表，
不 import 任何判分/门控/BKT/FSRS 模块（tests/test_notebook_cowriter_no_gating.py 守）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Notebook, NotebookRecord

SOURCE_TYPES: tuple[str, ...] = (
    "chat",
    "book_block",
    "solve",
    "visualize",
    "research",
    "cowriter",
    "free_text",
)
MAX_NOTEBOOKS_PER_STUDENT = 50
MAX_RECORDS_PER_NOTEBOOK = 2000
MAX_CONTENT_CHARS = 20000
MAX_METADATA_KEYS = 20
DEFAULT_NOTEBOOK_NAME = "我的笔记"


class NotebookError(Exception):
    """业务错误 → HTTP 映射（status_code + detail）。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def notebook_to_dict(nb: Notebook, record_count: Optional[int] = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": nb.id,
        "name": nb.name,
        "description": nb.description,
        "created_at": _iso(nb.created_at),
        "updated_at": _iso(nb.updated_at),
    }
    if record_count is not None:
        out["record_count"] = record_count
    return out


def record_to_dict(r: NotebookRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "notebook_id": r.notebook_id,
        "source_type": r.source_type,
        "source_id": r.source_id,
        "kc_id": r.kc_id,
        "title": r.title,
        "content": r.content,
        "metadata": r.meta or {},
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


def _clean_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise NotebookError(422, "笔记本名字不能为空")
    if len(cleaned) > 100:
        raise NotebookError(422, "笔记本名字最多 100 个字")
    return cleaned


def _clean_metadata(meta: Optional[dict]) -> dict:
    if not meta:
        return {}
    if not isinstance(meta, dict) or len(meta) > MAX_METADATA_KEYS:
        raise NotebookError(422, "metadata 必须是不超过 20 个键的对象")
    return meta


def validate_record_fields(source_type: str, content: str) -> str:
    if source_type not in SOURCE_TYPES:
        raise NotebookError(422, f"未知来源类型：{source_type}")
    body = (content or "").strip()
    if not body:
        raise NotebookError(422, "笔记内容不能为空")
    if len(body) > MAX_CONTENT_CHARS:
        raise NotebookError(422, f"单条笔记最多 {MAX_CONTENT_CHARS} 字")
    return body


async def _owned_notebook(db: AsyncSession, student_id: uuid.UUID, notebook_id: str) -> Notebook:
    nb = (
        await db.execute(select(Notebook).where(Notebook.id == notebook_id))
    ).scalar_one_or_none()
    if nb is None:
        raise NotebookError(404, "笔记本不存在")
    if nb.student_id != student_id:
        raise NotebookError(403, "这不是你的笔记本")
    return nb


async def list_notebooks(db: AsyncSession, student_id: uuid.UUID) -> list[dict]:
    counts = (
        select(NotebookRecord.notebook_id, func.count().label("n"))
        .where(NotebookRecord.student_id == student_id)
        .group_by(NotebookRecord.notebook_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Notebook, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.notebook_id == Notebook.id)
            .where(Notebook.student_id == student_id)
            .order_by(Notebook.updated_at.desc())
        )
    ).all()
    return [notebook_to_dict(nb, int(n)) for nb, n in rows]


async def create_notebook(
    db: AsyncSession, student_id: uuid.UUID, *, name: str, description: Optional[str] = None
) -> dict:
    cleaned = _clean_name(name)
    n = (
        await db.execute(
            select(func.count()).select_from(Notebook).where(Notebook.student_id == student_id)
        )
    ).scalar_one()
    if n >= MAX_NOTEBOOKS_PER_STUDENT:
        raise NotebookError(409, f"最多建 {MAX_NOTEBOOKS_PER_STUDENT} 个笔记本")
    nb = Notebook(
        id=f"nb_{uuid.uuid4().hex[:16]}",
        student_id=student_id,
        name=cleaned,
        description=(description or None),
    )
    db.add(nb)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise NotebookError(409, "已经有同名的笔记本了") from None
    await db.refresh(nb)
    return notebook_to_dict(nb, 0)


async def get_notebook(
    db: AsyncSession, student_id: uuid.UUID, notebook_id: str, *, limit: int = 200, offset: int = 0
) -> dict:
    nb = await _owned_notebook(db, student_id, notebook_id)
    total = (
        await db.execute(
            select(func.count())
            .select_from(NotebookRecord)
            .where(NotebookRecord.notebook_id == nb.id, NotebookRecord.student_id == student_id)
        )
    ).scalar_one()
    recs = (
        (
            await db.execute(
                select(NotebookRecord)
                .where(NotebookRecord.notebook_id == nb.id, NotebookRecord.student_id == student_id)
                .order_by(NotebookRecord.created_at.desc())
                .limit(max(1, min(limit, 500)))
                .offset(max(0, offset))
            )
        )
        .scalars()
        .all()
    )
    out = notebook_to_dict(nb, int(total))
    out["records"] = [record_to_dict(r) for r in recs]
    return out


async def update_notebook(
    db: AsyncSession,
    student_id: uuid.UUID,
    notebook_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    nb = await _owned_notebook(db, student_id, notebook_id)
    if name is not None:
        nb.name = _clean_name(name)
    if description is not None:
        nb.description = description or None
    nb.updated_at = _now()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise NotebookError(409, "已经有同名的笔记本了") from None
    return notebook_to_dict(nb)


async def delete_notebook(db: AsyncSession, student_id: uuid.UUID, notebook_id: str) -> None:
    nb = await _owned_notebook(db, student_id, notebook_id)
    await db.execute(
        delete(NotebookRecord).where(
            NotebookRecord.notebook_id == nb.id, NotebookRecord.student_id == student_id
        )
    )
    await db.execute(
        delete(Notebook).where(Notebook.id == nb.id, Notebook.student_id == student_id)
    )


async def add_record(
    db: AsyncSession,
    student_id: uuid.UUID,
    notebook_id: str,
    *,
    source_type: str,
    content: str,
    source_id: Optional[str] = None,
    kc_id: Optional[str] = None,
    title: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    body = validate_record_fields(source_type, content)
    nb = await _owned_notebook(db, student_id, notebook_id)
    n = (
        await db.execute(
            select(func.count())
            .select_from(NotebookRecord)
            .where(NotebookRecord.notebook_id == nb.id)
        )
    ).scalar_one()
    if n >= MAX_RECORDS_PER_NOTEBOOK:
        raise NotebookError(409, f"一个笔记本最多 {MAX_RECORDS_PER_NOTEBOOK} 条笔记")
    rec = NotebookRecord(
        id=f"nr_{uuid.uuid4().hex[:16]}",
        notebook_id=nb.id,
        student_id=student_id,
        source_type=source_type,
        source_id=(source_id or None),
        kc_id=(kc_id or None),
        title=(title or None),
        content=body,
        meta=_clean_metadata(metadata),
    )
    db.add(rec)
    nb.updated_at = _now()
    await db.flush()
    await db.refresh(rec)
    return record_to_dict(rec)


async def save_to_notebook(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    notebook_id: Optional[str],
    notebook_name: Optional[str],
    source_type: str,
    content: str,
    source_id: Optional[str] = None,
    kc_id: Optional[str] = None,
    title: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """「存到笔记本」一键入口：给 notebook_id 就存那本；否则按名字找自己的本子，
    没有就新建（默认名「我的笔记」）。"""
    validate_record_fields(source_type, content)
    if notebook_id:
        target = notebook_id
    else:
        name = _clean_name(notebook_name or DEFAULT_NOTEBOOK_NAME)
        existing = (
            await db.execute(
                select(Notebook).where(Notebook.student_id == student_id, Notebook.name == name)
            )
        ).scalar_one_or_none()
        target = existing.id if existing else (await create_notebook(db, student_id, name=name))["id"]
    rec = await add_record(
        db,
        student_id,
        target,
        source_type=source_type,
        content=content,
        source_id=source_id,
        kc_id=kc_id,
        title=title,
        metadata=metadata,
    )
    return {"notebook_id": target, "record": rec}


async def _owned_record(
    db: AsyncSession, student_id: uuid.UUID, notebook_id: str, record_id: str
) -> NotebookRecord:
    await _owned_notebook(db, student_id, notebook_id)
    rec = (
        await db.execute(
            select(NotebookRecord).where(
                NotebookRecord.id == record_id, NotebookRecord.notebook_id == notebook_id
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        raise NotebookError(404, "笔记不存在")
    if rec.student_id != student_id:
        raise NotebookError(403, "这不是你的笔记")
    return rec


async def update_record(
    db: AsyncSession,
    student_id: uuid.UUID,
    notebook_id: str,
    record_id: str,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> dict:
    rec = await _owned_record(db, student_id, notebook_id, record_id)
    if content is not None:
        rec.content = validate_record_fields(rec.source_type, content)
    if title is not None:
        rec.title = title or None
    rec.updated_at = _now()
    await db.flush()
    return record_to_dict(rec)


async def delete_record(
    db: AsyncSession, student_id: uuid.UUID, notebook_id: str, record_id: str
) -> None:
    rec = await _owned_record(db, student_id, notebook_id, record_id)
    await db.execute(
        delete(NotebookRecord).where(
            NotebookRecord.id == rec.id, NotebookRecord.student_id == student_id
        )
    )

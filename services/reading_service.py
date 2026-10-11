"""Immersive Reading（Layer 4）：沉浸式阅读的数据面（DeepTutor 对标）。

- 阅读来源：编译好的活书（books，ready/partial）+ 没有活书的教材原文分块
  （textbook_chunks，只读系统教材 owner_student_id IS NULL，绝不读别人上传的私有文件）。
- 教材分块按 chunk 顺序线性化为"阅读块"，跳过目录页/乱码页/过短碎片
  （复用 knowledge_hub_search 的同一套判据），每块附 ku_chunk_matches 匹配到的
  知识点 id（供"检查一下"走既有 RequestQuestion → SubmitAnswer）。
- 阅读位置：reading_positions（每人每来源一行，upsert）。

红线：阅读位置只是进度，不是学习证据——本模块不读不写 kc_mastery / gate.* /
process_interaction，不影响任何门控（tests/test_immersive_reading.py 静态断言）。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_hub_search import _clean_ratio, _is_toc_chunk

SOURCE_KINDS = ("book", "textbook")
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")
MAX_PAGE = 100
MIN_CHARS = 40
MIN_CLEAN_RATIO = 0.85
KCS_PER_BLOCK = 3

_CJK = "\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u2014\u2026\u201c\u201d"
_CJK_CHAR = re.compile(rf"[{_CJK}]")
_SPACE_CJK = re.compile(rf"(?<=[{_CJK}]) +(?=[{_CJK}])")
_PARA_SPLIT = re.compile(r"\n\s*\n")
_SENT_END = ("。", "！", "？", "：", "”")
_DOT_LEADER = re.compile(r"(?:\.{5,}|…{3,}|·{5,})")


class ReadingError(ValueError):
    """参数不合法（→ 422）。"""


def tidy_chunk_text(raw: str) -> str:
    """PDF 抽取文本的确定性清理。

    PDF 每个视觉行都断行（还常把"图 0-2"拆成单字符行）。段内按行拼接：任一侧是
    中文/全角字符直接相连，否则补一个空格；行尾是句末标点（。！？：”）视为段落结束；
    中文字间的单空格去掉。
    """
    s = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs: list[str] = []
    for block in _PARA_SPLIT.split(s):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        cur = ""
        prev_len = 0
        for ln in lines:
            if not cur:
                cur = ln
            elif cur.endswith(_SENT_END) and len(ln) > 3:
                paragraphs.append(cur)
                cur = ln
            elif (
                _CJK_CHAR.match(cur[-1])
                or _CJK_CHAR.match(ln[0])
                or len(ln) <= 2
                or prev_len <= 2
            ):
                cur += ln  # 中文相连；单字符碎行（"图/0/-/2"）也直接相连
            else:
                cur += " " + ln
            prev_len = len(ln)
        if cur:
            paragraphs.append(cur)
    return "\n\n".join(_SPACE_CJK.sub("", p) for p in paragraphs)


def is_readable_chunk(content: str) -> bool:
    body = (content or "").strip()
    if len(body) < MIN_CHARS:
        return False
    if _is_toc_chunk(body) or len(_DOT_LEADER.findall(body)) >= 2:
        return False
    return _clean_ratio(body) >= MIN_CLEAN_RATIO


class _Chunk:
    __slots__ = ("id", "page_number", "section_title", "content")

    def __init__(self, id: str, page_number: Any, section_title: Any, content: str):
        self.id = id
        self.page_number = page_number
        self.section_title = section_title
        self.content = content


def dedupe_overlaps(rows: Sequence[Any]) -> list[_Chunk]:
    """分块入库时同页相邻 chunk 有重叠（char_start < 上一块 char_end）。重叠部分只保留
    一次：剩余尾巴并回同页上一块，完全被覆盖的块丢掉——否则沉浸阅读会把同一句读两遍。"""
    out: list[_Chunk] = []
    last_key: tuple[Any, Any] | None = None
    last_end: int | None = None
    for r in rows:
        key = (r.file_id, r.page_number)
        start, end = r.char_start, r.char_end
        if (
            out
            and key == last_key
            and last_end is not None
            and start is not None
            and end is not None
            and start < last_end
        ):
            if end > last_end:
                out[-1].content += r.content[last_end - start :]
                last_end = end
            continue
        out.append(_Chunk(r.id, r.page_number, r.section_title, r.content))
        last_key, last_end = key, end
    return out


def _check_source(kind: str, source_id: str) -> None:
    if kind not in SOURCE_KINDS:
        raise ReadingError("source_kind 只能是 book 或 textbook")
    if not SOURCE_ID_RE.match(source_id or ""):
        raise ReadingError("source_id 不合法")


async def list_sources(db: AsyncSession, student_id: uuid.UUID) -> dict[str, Any]:
    """书单 + 可直接读原文的教材 + 本人的阅读位置（"继续读"）。"""
    books = (
        await db.execute(
            text("""
        SELECT b.id, b.textbook_id, b.title, b.status, t.subject, t.grade, t.book_name
        FROM books b LEFT JOIN textbooks t ON t.id = b.textbook_id
        WHERE b.status IN ('ready', 'partial')
        ORDER BY b.created_at DESC
    """)
        )
    ).fetchall()
    textbooks = (
        await db.execute(
            text("""
        SELECT t.id, t.subject, t.grade, t.book_name,
               COALESCE(SUM(f.chunk_count), 0) AS n_chunks,
               EXISTS (SELECT 1 FROM books b WHERE b.textbook_id = t.id
                       AND b.status IN ('ready', 'partial')) AS has_book
        FROM textbooks t
        JOIN textbook_files f ON f.textbook_id = t.id
        WHERE f.owner_student_id IS NULL AND COALESCE(f.chunk_count, 0) > 0
        GROUP BY t.id, t.subject, t.grade, t.book_name
        ORDER BY t.subject, t.id
    """)
        )
    ).fetchall()
    positions = (
        await db.execute(
            text("""
        SELECT source_kind, source_id, block_index, block_id, total_blocks, updated_at
        FROM reading_positions WHERE student_id = :sid
        ORDER BY updated_at DESC LIMIT 50
    """),
            {"sid": student_id},
        )
    ).fetchall()
    return {
        "books": [
            {
                "book_id": r.id,
                "textbook_id": r.textbook_id,
                "title": r.title,
                "status": r.status,
                "subject": r.subject,
                "grade": r.grade,
                "book_name": r.book_name,
            }
            for r in books
        ],
        "textbooks": [
            {
                "textbook_id": r.id,
                "subject": r.subject,
                "grade": r.grade,
                "book_name": r.book_name,
                "n_chunks": int(r.n_chunks or 0),
                "has_book": bool(r.has_book),
            }
            for r in textbooks
        ],
        "positions": [_position_dict(r) for r in positions],
    }


async def textbook_blocks(
    db: AsyncSession, textbook_id: str, *, offset: int = 0, limit: int = 40
) -> dict[str, Any] | None:
    """教材原文 → 线性阅读块（分页）。教材不存在/无系统分块 → None。"""
    _check_source("textbook", textbook_id)
    if offset < 0 or not (1 <= limit <= MAX_PAGE):
        raise ReadingError("offset/limit 不合法")
    meta = (
        await db.execute(
            text("SELECT id, subject, grade, book_name FROM textbooks WHERE id = :tid"),
            {"tid": textbook_id},
        )
    ).fetchone()
    if meta is None:
        return None
    rows = (
        await db.execute(
            text("""
        SELECT c.id, c.file_id, c.chunk_index, c.page_number, c.section_title,
               c.content, c.char_start, c.char_end
        FROM textbook_chunks c
        JOIN textbook_files f ON f.id = c.file_id
        WHERE f.textbook_id = :tid AND f.owner_student_id IS NULL
        ORDER BY f.uploaded_at, f.id, c.chunk_index
    """),
            {"tid": textbook_id},
        )
    ).fetchall()
    readable = [r for r in dedupe_overlaps(rows) if is_readable_chunk(r.content)]
    if not readable:
        return None
    page = readable[offset : offset + limit]
    kc_map: dict[str, list[str]] = {}
    if page:
        matches = (
            await db.execute(
                text("""
            SELECT chunk_id, ku_id FROM ku_chunk_matches
            WHERE chunk_id = ANY(:ids)
            ORDER BY chunk_id, score DESC, ku_id
        """),
                {"ids": [r.id for r in page]},
            )
        ).fetchall()
        for m in matches:
            lst = kc_map.setdefault(m.chunk_id, [])
            if len(lst) < KCS_PER_BLOCK and m.ku_id not in lst:
                lst.append(m.ku_id)
    return {
        "textbook": {
            "textbook_id": meta.id,
            "subject": meta.subject,
            "grade": meta.grade,
            "book_name": meta.book_name,
        },
        "total": len(readable),
        "offset": offset,
        "blocks": [
            {
                "block_id": r.id,
                "index": offset + i,
                "block_type": "text",
                "section_title": (r.section_title or "").strip() or None,
                "page_number": r.page_number,
                "payload": {"text": tidy_chunk_text(r.content)},
                "kc_ids": kc_map.get(r.id, []),
            }
            for i, r in enumerate(page)
        ],
    }


def _position_dict(r: Any) -> dict[str, Any]:
    return {
        "source_kind": r.source_kind,
        "source_id": r.source_id,
        "block_index": r.block_index,
        "block_id": r.block_id,
        "total_blocks": r.total_blocks,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


async def get_position(
    db: AsyncSession, student_id: uuid.UUID, kind: str, source_id: str
) -> dict[str, Any] | None:
    _check_source(kind, source_id)
    row = (
        await db.execute(
            text("""
        SELECT source_kind, source_id, block_index, block_id, total_blocks, updated_at
        FROM reading_positions
        WHERE student_id = :sid AND source_kind = :k AND source_id = :s
    """),
            {"sid": student_id, "k": kind, "s": source_id},
        )
    ).fetchone()
    return _position_dict(row) if row else None


async def _source_exists(db: AsyncSession, kind: str, source_id: str) -> bool:
    sql = (
        "SELECT 1 FROM books WHERE id = :s"
        if kind == "book"
        else "SELECT 1 FROM textbooks WHERE id = :s"
    )
    return (await db.execute(text(sql), {"s": source_id})).first() is not None


async def save_position(
    db: AsyncSession,
    student_id: uuid.UUID,
    kind: str,
    source_id: str,
    *,
    block_index: int,
    block_id: str | None = None,
    total_blocks: int | None = None,
) -> dict[str, Any]:
    """upsert 本人的阅读位置（只是进度，不写任何学习证据）。来源不存在 → ReadingError。"""
    _check_source(kind, source_id)
    if not (0 <= block_index <= 100_000):
        raise ReadingError("block_index 不合法")
    if total_blocks is not None and not (0 <= total_blocks <= 100_000):
        raise ReadingError("total_blocks 不合法")
    if total_blocks is not None and total_blocks > 0 and block_index >= total_blocks:
        raise ReadingError("block_index 超出 total_blocks")
    if block_id is not None and not SOURCE_ID_RE.match(block_id):
        raise ReadingError("block_id 不合法")
    if not await _source_exists(db, kind, source_id):
        raise ReadingError("阅读来源不存在")
    row = (
        await db.execute(
            text("""
        INSERT INTO reading_positions
            (student_id, source_kind, source_id, block_index, block_id, total_blocks, updated_at)
        VALUES (:sid, :k, :s, :i, :b, :t, now())
        ON CONFLICT (student_id, source_kind, source_id) DO UPDATE SET
            block_index = EXCLUDED.block_index,
            block_id = EXCLUDED.block_id,
            total_blocks = EXCLUDED.total_blocks,
            updated_at = now()
        RETURNING source_kind, source_id, block_index, block_id, total_blocks, updated_at
    """),
            {
                "sid": student_id,
                "k": kind,
                "s": source_id,
                "i": block_index,
                "b": block_id,
                "t": total_blocks,
            },
        )
    ).fetchone()
    return _position_dict(row)

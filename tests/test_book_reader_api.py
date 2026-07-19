"""W3 Part B B4 测试：ListBooks/GetBook（/studio/book 阅读器的只读数据源）。

真实 DB 数据：先用一个假 caller 跑一次真实 book_compile 编出一本小书，再验证
两个读接口能正确取回，包括 R1-R4 三态标注随书一起被正确读出。测试结束清理
掉这本测试书（不留生产垃圾数据，同 B3 测试约定）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from omodul.book_compile import BookCompileConfig, BookCompileInput, book_compile
from services.mcp_router import tool_get_book, tool_list_books

REAL_TEXTBOOK_ID = "RENJIAO-G1-MATH-S"


def _fake_caller():
    async def call(*, messages, system=None, max_tokens=800):
        return {
            "content": json.dumps(
                {"title": "阅读器测试书", "estimated_chapters": 1}, ensure_ascii=False
            ),
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }

    return call


@pytest.fixture
async def compiled_book(tmp_path: Path):
    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id=REAL_TEXTBOOK_ID)
        result = await book_compile(
            config, BookCompileInput(db=db, caller=_fake_caller()), tmp_path
        )
        assert result["status"] == "completed"
        book_id = result["book_id"]

    yield book_id

    async with SessionLocal() as db:
        await db.execute(sa_text("DELETE FROM books WHERE id=:id"), {"id": book_id})
        await db.commit()


@pytest.mark.asyncio
async def test_list_books_includes_compiled_book(compiled_book):
    async with SessionLocal() as db:
        result = await tool_list_books(db)

    ids = [b["book_id"] for b in result["books"]]
    assert compiled_book in ids
    entry = next(b for b in result["books"] if b["book_id"] == compiled_book)
    assert entry["textbook_id"] == REAL_TEXTBOOK_ID
    assert entry["status"] in ("ready", "partial")
    # 列表页不带 citations 细节——避免整本书内容都传下来
    assert "chapters" not in entry


@pytest.mark.asyncio
async def test_get_book_returns_nested_chapters_and_blocks_with_citations(
    compiled_book,
):
    async with SessionLocal() as db:
        result = await tool_get_book(db, compiled_book)

    book = result["book"]
    assert book is not None
    assert book["book_id"] == compiled_book
    assert len(book["chapters"]) > 0

    for chapter in book["chapters"]:
        assert "blocks" in chapter
        for block in chapter["blocks"]:
            assert block["block_type"] in (
                "text",
                "callout",
                "figure",
                "quiz",
                "flash_cards",
                "guided",
            )
            for citation in block["citations"]:
                # R1：任何持久化下来的引用分数不可能低于 0.60
                assert citation["score"] >= 0.60
                # R3/R4：三态标注必须是这两个合法值之一
                assert citation["citation_state"] in ("inferred_unverified", "verified")
                # 出处可点开需要的三个字段都在
                assert "pdf_id" in citation
                assert "page_number" in citation
                assert "char_start" in citation
                assert "char_end" in citation


@pytest.mark.asyncio
async def test_get_book_unknown_id_returns_none_not_error():
    async with SessionLocal() as db:
        result = await tool_get_book(db, "does-not-exist")

    assert result["book"] is None


@pytest.mark.asyncio
async def test_get_book_and_list_books_have_no_gating_parameters_and_dont_affect_is_mastered():
    """B-15：门控不受 Book/检索影响。ListBooks/GetBook 都没有 student_id/
    gating 相关参数（结构性不耦合），调用前后 is_mastered 判定不变。
    """
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered
    from mneme_core.oprim.models import (
        BktPosterior,
        KnowledgePoint,
        KnowledgeType,
        LearningProgress,
    )

    for fn in (tool_get_book, tool_list_books):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any("student" in p or "gate" in p or "mastery" in p for p in params)

    kp = KnowledgePoint(id="k1", name="k1", type=KnowledgeType.PROCEDURE)
    progress = LearningProgress(
        student_id="s1",
        modules=[],
        bkt={"k1": BktPosterior(p_learned=0.95, sigma=0.01, n_obs=5)},
    )
    before = is_mastered(progress, kp)
    async with SessionLocal() as db:
        await tool_list_books(db)
    after = is_mastered(progress, kp)
    assert before == after is True

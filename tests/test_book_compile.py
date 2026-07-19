"""W3 Part B B3 测试：omodul.book_compile 四支柱 + async C1-C6 并发规矩。

用真实 DB 数据（已索引教材/真实 knowledge_clusters）+ scripted fake async
caller（不依赖真实 provider，同 B1/B2 测试约定）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from omodul.book_compile import BookCompileConfig, BookCompileInput, book_compile

REAL_TEXTBOOK_ID = "RENJIAO-G1-MATH-S"  # 最小的已索引教材，跑得快


def _fake_caller(*, fixed_content=None, delay: float = 0.0):
    """usage 字段带真实 token 数——用于验证 cost 支柱真的累加（不是恒 0）。"""

    async def call(*, messages, system=None, max_tokens=800):
        if delay:
            await asyncio.sleep(delay)
        content = fixed_content if fixed_content is not None else '{"title":"t"}'
        return {
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    return call


async def _cleanup_book(db, book_id: str) -> None:
    await db.execute(sa_text("DELETE FROM books WHERE id=:id"), {"id": book_id})
    await db.commit()


@pytest.mark.asyncio
async def test_book_compile_end_to_end_persists_book(tmp_path: Path):
    """B-1/B-9：一本书端到端编译，四支柱齐全，cost 非零。"""
    caller = _fake_caller(
        fixed_content=json.dumps(
            {
                "title": "测试书",
                "description": "d",
                "scope": "s",
                "target_level": "G1",
                "estimated_chapters": 1,
                "rationale": "r",
            },
            ensure_ascii=False,
        )
    )

    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id=REAL_TEXTBOOK_ID)
        input_data = BookCompileInput(db=db, caller=caller)
        result = await book_compile(config, input_data, tmp_path)

        book_id = result.get("book_id")
        try:
            assert result["status"] == "completed"
            assert result["fingerprint"]
            assert result["decision_trail"]["steps"] > 0
            assert result["report_path"]
            assert result["cost_usd"] > 0  # cost 支柱非零——DeepTutor 没有这个支柱，别漏

            book_row = (
                await db.execute(
                    sa_text("SELECT * FROM books WHERE id=:id"), {"id": book_id}
                )
            ).fetchone()
            assert book_row is not None
            assert book_row.cost_usd > 0
            assert book_row.fingerprint == result["fingerprint"]

            chapters = (
                await db.execute(
                    sa_text(
                        "SELECT * FROM book_chapters WHERE book_id=:id ORDER BY display_order"
                    ),
                    {"id": book_id},
                )
            ).fetchall()
            assert len(chapters) == result["n_chapters"] > 0

            blocks = (
                await db.execute(
                    sa_text(
                        "SELECT * FROM book_blocks WHERE chapter_id IN "
                        "(SELECT id FROM book_chapters WHERE book_id=:id)"
                    ),
                    {"id": book_id},
                )
            ).fetchall()
            assert len(blocks) > 0
        finally:
            await _cleanup_book(db, book_id)


@pytest.mark.asyncio
async def test_unknown_textbook_id_fails_without_raising(tmp_path: Path):
    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id="does-not-exist")
        input_data = BookCompileInput(db=db, caller=_fake_caller())
        result = await book_compile(config, input_data, tmp_path)

    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"


@pytest.mark.asyncio
async def test_cost_accumulates_correctly_under_concurrent_chapter_compilation(
    tmp_path: Path,
):
    """C1：并发编译多章时，cost 必须正确累加到同一个 CostTracker——不能因为
    ContextVar 在并发 Task 间的传播方式而漏计或重复计。用带随机延迟的 caller
    强制乱序完成，验证最终 cost_usd 仍等于"实际调用次数 * 每次开销"。
    """
    caller = _fake_caller(
        fixed_content=json.dumps(
            {"title": "t", "estimated_chapters": 3}, ensure_ascii=False
        ),
        delay=0.01,
    )

    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id=REAL_TEXTBOOK_ID)
        input_data = BookCompileInput(db=db, caller=caller)
        result = await book_compile(config, input_data, tmp_path)
        book_id = result.get("book_id")
        try:
            assert result["status"] == "completed"
            # 每次真实调用记 100 in + 50 out tokens；cost 应该是 calls 次的整数倍，
            # 不是 0、也不是不完整的部分累加。
            expected_per_call = 100 * 3e-6 + 50 * 15e-6  # CostTracker 默认价格表兜底价
            # 不断言具体调用次数（page_plan/block 数量依赖真实 cluster 数据），
            # 只断言 cost 与"某个正整数次调用"精确吻合，不是被漏记的零头。
            n_calls_implied = result["cost_usd"] / expected_per_call
            assert abs(n_calls_implied - round(n_calls_implied)) < 1e-6
            assert round(n_calls_implied) > 1  # 确实有多次调用参与了累加
        finally:
            await _cleanup_book(db, book_id)


@pytest.mark.asyncio
async def test_step_no_follows_input_order_not_completion_order(tmp_path: Path):
    """C4：并发章节里，后面的章节故意配更长延迟，若先完成的章节抢占了小
    step_no，说明记录用了"记录时刻"而非"入参序"——这里验证 trail 里同一章节
    产生的 step_no 段（idx*100 起）不会因为完成顺序乱掉。
    """
    delays = [0.05, 0.01, 0.03]  # 第 0 章最慢，若干章节乱序完成
    calls = {"i": 0}

    async def caller(*, messages, system=None, max_tokens=800):
        # ideation/spine 用固定短延迟；章节级 page_plan/block 调用循环使用 delays
        i = calls["i"]
        calls["i"] += 1
        d = delays[i % len(delays)]
        await asyncio.sleep(d)
        return {
            "content": json.dumps(
                {"title": "t", "estimated_chapters": 3}, ensure_ascii=False
            ),
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }

    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id=REAL_TEXTBOOK_ID)
        input_data = BookCompileInput(db=db, caller=caller)
        result = await book_compile(config, input_data, tmp_path)
        book_id = result.get("book_id")
        try:
            assert result["status"] == "completed"
            trail_path = result["decision_trail"]["path"]
            steps = json.loads(Path(trail_path).read_text())
            page_planned_steps = [s for s in steps if s["event"] == "page_planned"]
            # 每章的 step_no 是 idx*100，idx 由输入序（spine.chapters 顺序）决定，
            # 与该章节实际完成的先后无关——按 chapter_id 首次出现的 step_no 排序后
            # 应该单调递增（因为 idx 本来就是 0,1,2...按顺序赋的）。
            step_nos = [s["step_no"] for s in page_planned_steps]
            assert step_nos == sorted(step_nos)
        finally:
            await _cleanup_book(db, book_id)


@pytest.mark.asyncio
async def test_cancellation_writes_trail_before_reraising(tmp_path: Path):
    """C2/C3：编译中途被取消，必须重抛 CancelledError，且 trail 文件已写入
    （shield 保证 write 不被连带取消打断）。
    """

    async def slow_caller(*, messages, system=None, max_tokens=800):
        await asyncio.sleep(1.0)
        return {"content": "{}", "usage": {"input_tokens": 1, "output_tokens": 1}}

    async with SessionLocal() as db:
        config = BookCompileConfig(textbook_id=REAL_TEXTBOOK_ID)
        input_data = BookCompileInput(db=db, caller=slow_caller)

        task = asyncio.create_task(book_compile(config, input_data, tmp_path))
        await asyncio.sleep(0.05)  # 让它进入 ideation 阶段的 LLM 调用
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        trail_files = list(tmp_path.glob("decision_trail_*.json"))
        assert len(trail_files) == 1
        steps = json.loads(trail_files[0].read_text())
        assert any(s["event"] == "cancelled" for s in steps)

"""omodul.book_compile —— Book Engine 编译（W3 Part B B3）。

Pillars: fingerprint, decision_trail, report, cost（**cost 是本 omodul 新增，
DeepTutor book/compiler.py 没有这个支柱**——每本书的 LLM/embedding/检索开销，
未来可售定价依据，不能漏）。

标准三件套签名 (config, input_data, output_dir) -> dict；失败不 raise（除
CancelledError，必须重抛，见下方 async 并发说明）。

对照 vendor/omodul/run_subagent_task.py（ContextVar 持有共享 CostTracker，
"same object ref, never replace"）+ book_understanding_synthesize.py
（CancelledError 时 trail.write 再重抛）——本模块把两者的模式合成一处，
应用到"多块并发编译"场景：

  C1 ContextVar 共享 CostTracker：本模块声明 _cost_var，在 book_compile()
     入口 set() 一次；实际记账发生在 _cost_tracking_caller() 这个包装函数里
     ——它包住调用方传入的原始 LLMCaller，每次真实 LLM 调用完成后从
     _cost_var.get() 取出**当前 context 里的那一个** CostTracker 对象并调用
     .add()（原地累加）。ideation/spine/page_plan/block 生成器全都只是调用
     "看起来和普通 caller 一样"的这个包装函数，不需要知道 CostTracker 存在
     ——记账在包装层完全透明地发生。规矩：任何地方都不允许对 _cost_var
     调用第二次 set()（尤其是并发子 Task 内部），那样会让该子 Task 此后的
     记账进新对象、脱离主 CostTracker，导致 cost 静默漏计。
  C2 CancelledError 重抛：绝不吞掉，捕获后必须 raise。
  C3 shield 落 trail：CancelledError 处理里 trail.write() 用 asyncio.shield
     包裹——取消信号已经在传播，若不 shield，trail 文件可能来不及写完就被
     连带取消，编译失败时反而丢了最需要的诊断信息。
  C4 step_no 按入参序：trail.record() 总是显式传 step_no=<该块在输入序列里
     的位置>，不依赖"记录时 len(steps)+1"的默认值——并发任务完成顺序不确定，
     若不显式传，trail 里的 step_no 会反映完成时序而非编译计划的逻辑顺序。
  C5 asyncio.gather 保序：gather() 返回的结果列表按输入顺序对应
     （文档保证的行为，不是 completion 顺序），持久化 chapter/block 时直接
     按这个顺序写 display_order，不需要额外排序。
  C6 结果收集全用返回值，不用可变外部列表被并发 task 直接 append——避免
     "谁先跑完谁先占位"的竞态；每个子任务的输出通过 return 传回，由主协程
     统一按 gather 的顺序落库。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from omodul._base import (
    BaseConfig,
    CostTracker,
    Trail,
    build_result,
    compute_fingerprint,
    write_report,
)

from mneme_core.oprim.models import (
    BlockSpec,
    BookProposal,
    BookSpine,
    ChapterSpec,
    ClusterSummary,
    TextbookMeta,
)
from mneme_core.oskill.book_ideation import book_ideation
from mneme_core.oskill.book_page_plan import book_page_plan
from mneme_core.oskill.book_spine import book_spine
from services.book_block_generators import BlockContext, generate_block

_cost_var: ContextVar[CostTracker] = ContextVar("book_compile_cost")


def _cost_tracking_caller(raw_caller: Any, *, model: str) -> Any:
    """包一层：每次真实 LLM 调用后，把 usage 记进 _cost_var.get() 当前那一个
    CostTracker（C1）。ideation/spine/page_plan/block 生成器拿到的就是这个
    包装函数，本身对 CostTracker 一无所知——cost 支柱因此不会被任何一处
    调用点"忘记记账"。
    """

    async def wrapped(*, messages, system=None, max_tokens=800):
        resp = await raw_caller(messages=messages, system=system, max_tokens=max_tokens)
        usage = resp.get("usage") or {}
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        if in_tok or out_tok:
            _cost_var.get().add(in_tok=in_tok, out_tok=out_tok, model=model)
        return resp

    return wrapped


class BookCompileConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "book_compile"
    _omodul_version: ClassVar[str] = "1.0.0"
    _enabled_pillars: ClassVar[set[str]] = {
        "fingerprint",
        "decision_trail",
        "report",
        "cost",
    }
    _fingerprint_fields: ClassVar[set[str]] = {
        "textbook_id",
        "ku_ids",
        "chunk_version",
        "review_version",
        "spine_version",
    }

    textbook_id: str


class BookCompileInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any  # AsyncSession，不是 pydantic 类型，仅用 arbitrary_types_allowed 透传
    caller: Any  # book_block_generators.LLMCaller（未包装的原始 provider caller）


async def _fetch_textbook_meta(
    db: AsyncSession, textbook_id: str
) -> Optional[TextbookMeta]:
    row = (
        await db.execute(
            sa_text(
                "SELECT id, subject, grade, book_name FROM textbooks WHERE id=:tid"
            ),
            {"tid": textbook_id},
        )
    ).fetchone()
    if row is None:
        return None
    return TextbookMeta(
        textbook_id=row.id,
        subject=row.subject,
        grade=row.grade,
        book_name=row.book_name,
    )


async def _fetch_cluster_summaries(
    db: AsyncSession, textbook_id: str
) -> list[ClusterSummary]:
    rows = (
        await db.execute(
            sa_text("""
        SELECT kc.id, kc.name, kc.display_order, count(ku.id) AS ku_count
        FROM knowledge_clusters kc
        LEFT JOIN knowledge_units ku ON ku.cluster_id = kc.id
        WHERE kc.textbook_id = :tid
        GROUP BY kc.id, kc.name, kc.display_order
        ORDER BY kc.display_order
    """),
            {"tid": textbook_id},
        )
    ).fetchall()

    clusters: list[ClusterSummary] = []
    for r in rows:
        names = (
            await db.execute(
                sa_text(
                    "SELECT name FROM knowledge_units WHERE cluster_id=:cid LIMIT 8"
                ),
                {"cid": r.id},
            )
        ).fetchall()
        clusters.append(
            ClusterSummary(
                cluster_id=r.id,
                name=r.name,
                display_order=r.display_order,
                ku_count=r.ku_count,
                ku_names_sample=[n[0] for n in names],
            )
        )
    return clusters


async def _fingerprint_inputs(
    db: AsyncSession, textbook_id: str, spine: BookSpine
) -> dict:
    """fingerprint 四要素：KC 集合 + chunk 版本 + spine 版本 + 挂接校订版本。
    任一变化都应让旧编译结果失效（换书/教材重新索引/人工校订挂接之后重编）。
    """
    ku_ids = (
        await db.execute(
            sa_text("""
        SELECT ku.id FROM knowledge_units ku
        JOIN knowledge_clusters kc ON kc.id = ku.cluster_id
        WHERE kc.textbook_id = :tid ORDER BY ku.id
    """),
            {"tid": textbook_id},
        )
    ).fetchall()
    ku_id_list = sorted(r[0] for r in ku_ids)

    chunk_version_row = (
        await db.execute(
            sa_text("""
        SELECT count(*), max(tc.embedded_at)
        FROM textbook_chunks tc
        JOIN textbook_files tf ON tf.id = tc.file_id
        WHERE tf.textbook_id = :tid
    """),
            {"tid": textbook_id},
        )
    ).fetchone()

    review_version_row = (
        await db.execute(
            sa_text("""
        SELECT count(*) FILTER (WHERE kcm.verified), max(kcm.verified_at)
        FROM ku_chunk_matches kcm
        JOIN knowledge_units ku ON ku.id = kcm.ku_id
        JOIN knowledge_clusters kc ON kc.id = ku.cluster_id
        WHERE kc.textbook_id = :tid
    """),
            {"tid": textbook_id},
        )
    ).fetchone()

    return {
        "textbook_id": textbook_id,
        "ku_ids": ku_id_list,
        "chunk_version": [chunk_version_row[0], str(chunk_version_row[1])],
        "review_version": [review_version_row[0], str(review_version_row[1])],
        "spine_version": spine.version,
    }


async def _compile_chapter_blocks(
    *,
    idx: int,
    db: AsyncSession,
    caller: Any,
    book_id: str,
    chapter: ChapterSpec,
    trail: Trail,
) -> tuple[ChapterSpec, list[BlockSpec], list[dict]]:
    """一章的完整流水：page_plan -> 逐块 generate_block。返回值供主协程按
    gather 顺序统一落库（C6：不用外部可变列表被并发 task 直接 append）。
    """
    blocks = await book_page_plan(caller, chapter=chapter)
    trail.record(
        event="page_planned",
        step_no=idx * 100,
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        n_blocks=len(blocks),
    )

    results: list[dict] = []
    for b_idx, block in enumerate(blocks):
        ctx = BlockContext(
            db=db, caller=caller, book_id=book_id, chapter=chapter, block=block
        )
        result = await generate_block(ctx)
        citations = (
            result.get("payload", {}).get("citations", [])
            if result.get("status") == "ready"
            else []
        )
        trail.record(
            event="block_compiled",
            step_no=idx * 100 + b_idx + 1,
            chapter_id=chapter.id,
            block_type=block.type.value,
            status=result.get("status"),
            error=result.get("error"),
            # R3/R4 审计留痕（B-11）：每处引用的挂接分 + 三态，不是笼统一个标签
            citations=[
                {
                    "chunk_id": c["chunk_id"],
                    "score": c["score"],
                    "citation_state": c["citation_state"],
                }
                for c in citations
            ],
        )
        results.append(result)

    return chapter, blocks, results


def _sort_trail_steps(trail: Trail) -> None:
    """C4 的落地保证：trail.record() 并发调用时按完成顺序 append，数组本身
    不是入参序——写盘前按 step_no 排一次序，让持久化的决策留痕真正可读
    （"第几步做了什么"），不是给人一份乱序但数值正确的原始日志。
    """
    trail.steps.sort(key=lambda s: s["step_no"])


async def _write_trail_async(trail: Trail, output_dir: Path) -> None:
    _sort_trail_steps(trail)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, trail.write, output_dir)


async def _persist_book(
    db: AsyncSession,
    *,
    book_id: str,
    meta: TextbookMeta,
    proposal: BookProposal,
    chapter_blocks: list[tuple[ChapterSpec, list[BlockSpec], list[dict]]],
    fingerprint: str,
    cost: CostTracker,
    status: str,
    decision_trail_path: Optional[str],
    report_path: Optional[str],
) -> None:
    """chapter_blocks 顺序 = spine.chapters 顺序 = gather 返回顺序（C5），
    display_order 直接用 enumerate 序号。
    """
    await db.execute(
        sa_text("""
        INSERT INTO books (id, textbook_id, title, description, scope, target_level,
                            status, fingerprint, cost_usd, decision_trail_path, report_path,
                            created_at, updated_at)
        VALUES (:id, :tid, :title, :desc, :scope, :level, :status, :fp, :cost,
                :trail_path, :report_path, now(), now())
    """),
        {
            "id": book_id,
            "tid": meta.textbook_id,
            "title": proposal.title,
            "desc": proposal.description,
            "scope": proposal.scope,
            "level": proposal.target_level,
            "status": status,
            "fp": fingerprint,
            "cost": cost.total_usd,
            "trail_path": decision_trail_path,
            "report_path": report_path,
        },
    )

    for ch_idx, (chapter, blocks, block_results) in enumerate(chapter_blocks):
        chapter_id = f"bc_{uuid.uuid4().hex[:12]}"
        await db.execute(
            sa_text("""
            INSERT INTO book_chapters (id, book_id, title, content_type, display_order,
                                        cluster_ids, learning_objectives, prerequisites,
                                        summary, created_at)
            VALUES (:id, :book_id, :title, :ctype, :order, :cids, :objs, :prereq, :summary, now())
        """),
            {
                "id": chapter_id,
                "book_id": book_id,
                "title": chapter.title,
                "ctype": chapter.content_type.value,
                "order": ch_idx,
                "cids": json.dumps(chapter.cluster_ids, ensure_ascii=False),
                "objs": json.dumps(chapter.learning_objectives, ensure_ascii=False),
                "prereq": json.dumps(chapter.prerequisites, ensure_ascii=False),
                "summary": chapter.summary,
            },
        )
        for blk_idx, (block, result) in enumerate(zip(blocks, block_results)):
            payload = (
                result.get("payload", {}) if result.get("status") == "ready" else {}
            )
            citations = payload.get("citations", [])
            await db.execute(
                sa_text("""
                INSERT INTO book_blocks (id, chapter_id, block_type, display_order,
                                          params, payload, citations, status, error, created_at)
                VALUES (:id, :chapter_id, :btype, :order, :params, :payload, :citations,
                        :status, :error, now())
            """),
                {
                    "id": f"bb_{uuid.uuid4().hex[:12]}",
                    "chapter_id": chapter_id,
                    "btype": block.type.value,
                    "order": blk_idx,
                    "params": json.dumps(block.params, ensure_ascii=False),
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                    "citations": json.dumps(citations, ensure_ascii=False),
                    "status": result.get("status", "error"),
                    "error": result.get("error"),
                },
            )
    await db.commit()


def _build_report(
    meta: TextbookMeta,
    proposal: BookProposal,
    spine: BookSpine,
    chapter_blocks: list[tuple[ChapterSpec, list[BlockSpec], list[dict]]],
    cost: CostTracker,
    n_block_errors: int,
) -> str:
    lines = [
        f"# {proposal.title}",
        "",
        f"**教材**: {meta.book_name}（{meta.subject}/{meta.grade}）  ",
        f"**章数**: {len(spine.chapters)}  ",
        f"**块生成失败数**: {n_block_errors}  ",
        f"**开销**: ${cost.total_usd:.4f}（{cost.calls} 次调用，"
        f"{cost.in_tokens}+{cost.out_tokens} tokens）  ",
        "",
        f"## 简介\n\n{proposal.description}\n",
        "## 章节",
        "",
    ]
    for chapter, blocks, results in chapter_blocks:
        ok = sum(1 for r in results if r.get("status") == "ready")
        lines.append(
            f"- **{chapter.title}**（{chapter.content_type.value}）：{ok}/{len(blocks)} 块生成成功"
        )
    return "\n".join(lines) + "\n"


def _notify(on_step: Any, step: str, state: str) -> None:
    if on_step is not None:
        try:
            on_step(step=step, state=state)
        except Exception:
            pass


async def book_compile(
    config: BookCompileConfig,
    input_data: BookCompileInput,
    output_dir: Path,
    *,
    on_step=None,
) -> dict:
    """B1(ideation/spine/page_planner) -> B2(block generation) 端到端编译一本书，
    持久化到 books/book_chapters/book_blocks。失败不 raise（CancelledError 除外）。
    """
    db: AsyncSession = input_data.db
    trail = Trail()
    cost = CostTracker()  # C1：本次编译全程只有这一个 CostTracker 实例
    _cost_var.set(cost)  # 只在这里 set 一次——子任务一律只读取、只 .add()

    caller = _cost_tracking_caller(input_data.caller, model=config.llm_model)

    try:
        meta = await _fetch_textbook_meta(db, config.textbook_id)
        if meta is None:
            return build_result(
                status="failed",
                error={
                    "type": "ValueError",
                    "message": f"unknown textbook_id {config.textbook_id}",
                },
                trail=trail,
                cost_usd=0.0,
            )

        clusters = await _fetch_cluster_summaries(db, config.textbook_id)
        if not clusters:
            return build_result(
                status="failed",
                error={
                    "type": "ValueError",
                    "message": "no knowledge_clusters for this textbook",
                },
                trail=trail,
                cost_usd=0.0,
            )

        trail.record(
            event="start",
            step_no=0,
            textbook_id=config.textbook_id,
            n_clusters=len(clusters),
        )
        _notify(on_step, "ideation", "started")

        proposal = await book_ideation(caller, meta=meta, clusters=clusters)
        trail.record(
            event="ideation_done",
            step_no=1,
            title=proposal.title,
            estimated_chapters=proposal.estimated_chapters,
        )
        _notify(on_step, "ideation", "done")

        book_id = f"bk_{uuid.uuid4().hex[:12]}"
        spine = await book_spine(
            caller, book_id=book_id, proposal=proposal, clusters=clusters
        )
        trail.record(event="spine_done", step_no=2, n_chapters=len(spine.chapters))
        _notify(on_step, "spine", "done")

        fingerprint_fields = await _fingerprint_inputs(db, config.textbook_id, spine)
        fingerprint = compute_fingerprint(fingerprint_fields)

        _notify(on_step, "compile_blocks", "started")

        # C1/C5/C6：所有章节并发编译，caller 闭包里的 _cost_var 对同一个
        # CostTracker 原地累加；asyncio.gather 按输入顺序返回结果。
        tasks = [
            asyncio.create_task(
                _compile_chapter_blocks(
                    idx=idx,
                    db=db,
                    caller=caller,
                    book_id=book_id,
                    chapter=chapter,
                    trail=trail,
                )
            )
            for idx, chapter in enumerate(spine.chapters)
        ]
        try:
            chapter_blocks = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            trail.record(event="cancelled")
            await asyncio.shield(_write_trail_async(trail, output_dir))
            raise

        _notify(on_step, "compile_blocks", "done")

        n_block_errors = sum(
            1
            for _, _, results in chapter_blocks
            for r in results
            if r.get("status") == "error"
        )
        status = "ready" if n_block_errors == 0 else "partial"

        report_content = _build_report(
            meta, proposal, spine, chapter_blocks, cost, n_block_errors
        )
        report_path = write_report(
            report_content,
            output_dir=output_dir,
            name=f"book_{fingerprint[:8]}",
            fmt="markdown",
        )

        _sort_trail_steps(trail)
        trail_path = trail.write(output_dir)

        await _persist_book(
            db,
            book_id=book_id,
            meta=meta,
            proposal=proposal,
            chapter_blocks=chapter_blocks,
            fingerprint=fingerprint,
            cost=cost,
            status=status,
            decision_trail_path=str(trail_path),
            report_path=str(report_path),
        )

        return build_result(
            status="completed",
            error=None,
            fingerprint=fingerprint,
            trail=trail,
            trail_path=trail_path,
            report_path=str(report_path),
            cost_usd=cost.total_usd,
            book_id=book_id,
            book_status=status,
            n_chapters=len(spine.chapters),
            n_block_errors=n_block_errors,
        )

    except asyncio.CancelledError:
        trail.record(event="cancelled")
        await asyncio.shield(_write_trail_async(trail, output_dir))
        raise
    except Exception as exc:
        trail.record(event="error", error_type=type(exc).__name__, message=str(exc))
        return build_result(
            status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
            trail=trail,
            cost_usd=cost.total_usd,
        )


__all__ = ["BookCompileConfig", "BookCompileInput", "book_compile"]

"""活书编译入口（layer-4 service）：给 vendor/omodul/book_compile 一个真实的入口。

职责划分（3O）：
- 编译本身（ideation→spine→page_plan→blocks→落库）全在 omodul.book_compile，本模块
  一行不改它，只做「谁能编、编几本、花多少钱、状态怎么追」这层产品外壳。
- 路由（services/routers/books.py）只做鉴权 + 调本模块；Celery 任务
  （tasks/book_tasks.py）只做 asyncio.run(run_compile_job(...))。

稳定 book_id：omodul.book_compile 在编译**结束时**才自己生成 book_id 并 INSERT books。
为了让入口一提交就能返回 book_id 供轮询，这里先插一行占位 books（status=queued），
编译完成后把 omodul 生成的那本书的章节挂到占位行上、摘要字段拷过来、删掉 omodul 那
一行——对外 book_id 自始至终不变，阅读器（ListBooks/GetBook）无需任何改动
（ListBooks 只列 ready/partial，占位行在编完之前天然不出现在书单里）。

状态机：queued → compiling → ready | partial | error。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_log = logging.getLogger(__name__)

PLACEHOLDER_PREFIX = "bkj_"
IN_FLIGHT = ("queued", "compiling")
# 卡在 queued/compiling 超过这么久的行不再视为「在编」（worker 崩溃/重启残留），
# 不再挡同教材的新提交，也不再计入全站在途预算；任务重投（acks_late，Redis
# visibility_timeout 默认 1h）时允许重新认领。必须 ≥ tasks.compile_book 的
# time_limit（3500s）：活着的编译不可能超过它，超过的只可能是被杀掉的残留。
STALE_AFTER_MINUTES = 60


class CompileRejected(Exception):
    """入口校验/限额拒绝：status_code 直接映射成 HTTP 状态。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class BookBudgetExceeded(RuntimeError):
    """单本编译 LLM 开销超出上限：之后的每次调用直接拒绝，止损。"""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def per_user_daily_limit() -> int:
    """每人每天可发起的编译次数（失败也算，失败同样花了钱）。admin 不受此限。"""
    return _env_int("MNEME_BOOK_COMPILE_DAILY_LIMIT", 3)


def per_book_cost_cap_usd() -> float:
    """单本编译 LLM 开销上限：超出即中止后续调用。实测一本小教材约 $0.57。"""
    return _env_float("MNEME_BOOK_COMPILE_MAX_USD", 2.5)


def min_output_tokens() -> int:
    """生产 caller 的 max_tokens 下限。

    omodul 生成器给的 max_tokens 是按非推理模型定的（150–800）。生产回退链里的推理
    模型（InternAI Agents-A1 等）会把这点额度全花在思考上、content 为空，于是整本书
    静默回退成静态模板（2026-10-11 实测：max_tokens=600/4000 都是空 content，
    finish_reason=length）。入口层把下限抬到这里，不改 vendor。
    """
    return _env_int("MNEME_BOOK_COMPILE_MIN_TOKENS", 6000)


def global_daily_cost_cap_usd() -> float:
    """全站每天经入口编译的总开销上限（已花 + 在途按单本上限预留）。"""
    return _env_float("MNEME_BOOK_COMPILE_DAILY_USD", 15.0)


def output_root() -> Path:
    """trail/report 的落盘目录。容器里 services/ 在 /app 下 → /app/data/book_compile。"""
    env = os.environ.get("MNEME_BOOK_OUTPUT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data" / "book_compile"


_TODAY_START_SQL = (
    "(date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')"
)
_FRESH_SQL = f"updated_at > now() - interval '{STALE_AFTER_MINUTES} minutes'"


async def list_compilable_textbooks(db: AsyncSession) -> list[dict]:
    """有知识簇（book_compile 的必需输入）的教材，附已编好的活书数。"""
    rows = (
        await db.execute(
            text("""
        SELECT t.id, t.subject, t.grade, t.book_name, t.edition,
               count(DISTINCT kc.id) AS n_clusters,
               count(ku.id) AS n_units,
               (SELECT count(*) FROM books b
                 WHERE b.textbook_id = t.id AND b.status IN ('ready', 'partial')) AS n_books
        FROM textbooks t
        JOIN knowledge_clusters kc ON kc.textbook_id = t.id
        LEFT JOIN knowledge_units ku ON ku.cluster_id = kc.id
        WHERE t.id NOT LIKE 'tb-lp-%' AND t.book_name <> '练习教材'
        GROUP BY t.id, t.subject, t.grade, t.book_name, t.edition
        ORDER BY t.subject, t.grade, t.book_name
    """)
        )
    ).fetchall()
    return [
        {
            "textbook_id": r.id,
            "subject": r.subject,
            "grade": r.grade,
            "book_name": r.book_name,
            "edition": r.edition,
            "n_clusters": int(r.n_clusters),
            "n_units": int(r.n_units),
            "n_books": int(r.n_books),
        }
        for r in rows
    ]


async def create_compile_job(
    db: AsyncSession, *, requested_by: str, textbook_id: str, is_admin: bool
) -> dict:
    """校验 + 限额 + 插占位行（commit）。返回 {book_id, status, deduplicated}。

    不负责入队——路由在 commit 之后调 enqueue_compile()，入队失败再 mark_error()。
    """
    tb = (
        await db.execute(
            text("SELECT id, book_name FROM textbooks WHERE id = :tid"),
            {"tid": textbook_id},
        )
    ).fetchone()
    if tb is None:
        raise CompileRejected(404, f"教材不存在：{textbook_id}")
    n_clusters = (
        await db.execute(
            text("SELECT count(*) FROM knowledge_clusters WHERE textbook_id = :tid"),
            {"tid": textbook_id},
        )
    ).scalar_one()
    if not n_clusters:
        raise CompileRejected(422, "这本教材还没有知识结构（knowledge_clusters），暂时编不了活书")

    # 同一用户的并发提交串行化，避免两个请求同时通过限额检查。
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"book_compile:{requested_by}"},
    )

    # 同一本教材已经在编：直接复用那个任务，不重复花钱。
    existing = (
        await db.execute(
            text(f"""
        SELECT id, status FROM books
        WHERE textbook_id = :tid AND status IN ('queued', 'compiling') AND {_FRESH_SQL}
        ORDER BY created_at DESC LIMIT 1
    """),
            {"tid": textbook_id},
        )
    ).fetchone()
    if existing is not None:
        await db.rollback()
        return {"book_id": existing.id, "status": existing.status, "deduplicated": True}

    if not is_admin:
        used = (
            await db.execute(
                text(f"""
            SELECT count(*) FROM books
            WHERE requested_by = :uid AND created_at >= {_TODAY_START_SQL}
        """),
                {"uid": requested_by},
            )
        ).scalar_one()
        limit = per_user_daily_limit()
        if used >= limit:
            raise CompileRejected(429, f"今天的活书生成次数已用完（每天 {limit} 本），明天再来")

    budget_row = (
        await db.execute(
            text(f"""
        SELECT coalesce(sum(cost_usd), 0),
               count(*) FILTER (WHERE status IN ('queued', 'compiling') AND {_FRESH_SQL})
        FROM books
        WHERE requested_by IS NOT NULL AND created_at >= {_TODAY_START_SQL}
    """)
        )
    ).fetchone()
    spent, in_flight = (budget_row[0], budget_row[1]) if budget_row is not None else (0, 0)
    projected = float(spent) + (int(in_flight) + 1) * per_book_cost_cap_usd()
    if projected > global_daily_cost_cap_usd():
        raise CompileRejected(429, "今天全站活书生成预算已用完，请明天再试")

    book_id = f"{PLACEHOLDER_PREFIX}{uuid.uuid4().hex[:12]}"
    await db.execute(
        text("""
        INSERT INTO books (id, textbook_id, title, status, requested_by, created_at, updated_at)
        VALUES (:id, :tid, :title, 'queued', :uid, now(), now())
    """),
        {
            "id": book_id,
            "tid": textbook_id,
            "title": f"{tb.book_name}（生成中）"[:200],
            "uid": requested_by,
        },
    )
    await db.commit()
    return {"book_id": book_id, "status": "queued", "deduplicated": False}


def enqueue_compile(book_id: str) -> None:
    """投递 Celery 任务。单独成函数便于测试替换。"""
    from tasks.book_tasks import compile_book_task

    compile_book_task.delay(book_id)


async def mark_error(db: AsyncSession, book_id: str, message: str, cost_usd: float = 0.0) -> None:
    await db.execute(
        text("""
        UPDATE books SET status = 'error', error = :err,
               cost_usd = greatest(cost_usd, :cost), updated_at = now()
        WHERE id = :id
    """),
        {"id": book_id, "err": message[:2000], "cost": cost_usd},
    )
    await db.commit()


async def get_compile_status(db: AsyncSession, book_id: str) -> Optional[dict]:
    row = (
        await db.execute(
            text(f"""
        SELECT b.id, b.textbook_id, b.title, b.status, b.error, b.cost_usd,
               b.requested_by, b.created_at, b.updated_at, t.book_name,
               (SELECT count(*) FROM book_chapters c WHERE c.book_id = b.id) AS n_chapters,
               (SELECT count(*) FROM book_blocks k JOIN book_chapters c ON c.id = k.chapter_id
                 WHERE c.book_id = b.id) AS n_blocks,
               (SELECT count(*) FROM book_blocks k JOIN book_chapters c ON c.id = k.chapter_id
                 WHERE c.book_id = b.id AND k.status = 'error') AS n_block_errors,
               (b.status IN ('queued', 'compiling')
                AND b.updated_at <= now() - interval '{STALE_AFTER_MINUTES} minutes') AS stale
        FROM books b LEFT JOIN textbooks t ON t.id = b.textbook_id
        WHERE b.id = :id
    """),
            {"id": book_id},
        )
    ).fetchone()
    if row is None:
        return None
    return {
        "book_id": row.id,
        "textbook_id": row.textbook_id,
        "book_name": row.book_name,
        "title": row.title,
        "status": row.status,
        "stale": bool(row.stale),
        "error": row.error,
        "cost_usd": round(float(row.cost_usd or 0.0), 4),
        "n_chapters": int(row.n_chapters),
        "n_blocks": int(row.n_blocks),
        "n_block_errors": int(row.n_block_errors),
        "requested_by": row.requested_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def llm_concurrency() -> int:
    """活书编译同时在途的 LLM 调用上限（跨 job、跨 worker 进程）。

    2026-10-11：omodul.book_compile 按章节 asyncio.gather 并发生成，7 章 = 7 个
    同时在途的推理模型调用，全部超时 → 共享 provider 的熔断器被打开，其它功能
    （讲解/批改）跟着一起 30s 不可用。默认 3。
    """
    return max(1, min(_env_int("MNEME_BOOK_COMPILE_LLM_CONCURRENCY", 3), 16))


def _slots_dir() -> Path:
    raw = os.environ.get("MNEME_BOOK_COMPILE_SLOT_DIR") or os.path.join(
        tempfile.gettempdir(), "mneme-book-llm-slots"
    )
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextlib.asynccontextmanager
async def llm_slot(poll_seconds: float = 0.5):
    """跨进程计数信号量：N 个 slot 文件，每次调用持有其中一个的 flock。

    worker 是 prefork（--concurrency=2），进程内 asyncio.Semaphore 管不到另一个
    子进程；flock 锁跟着打开的文件描述走，进程被杀时内核自动释放，不会泄漏 slot。
    （同进程内两个 fd 对同一文件 flock 也互斥，所以同一 job 的并发章节同样受限。）
    """
    import fcntl

    n = llm_concurrency()
    root = _slots_dir()
    fh = None
    while fh is None:
        for i in range(n):
            candidate = open(root / f"slot-{i}.lock", "a+")  # noqa: SIM115 - held across await
            try:
                fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                candidate.close()
                continue
            fh = candidate
            break
        if fh is None:
            await asyncio.sleep(poll_seconds)
    try:
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


class BudgetCaller:
    """包住生产 caller：按 omodul 同一价格表累计开销，超过上限后拒绝后续调用。

    omodul.book_compile 自己也记账（cost 支柱），但只记不拦；入口层需要的是止损。

    同时数成功/失败调用：omodul 的各生成器在 LLM 失败**或返回空 content** 时会回退
    静态模板并仍标 ready——provider 挂掉/推理模型额度不够时会编出一本「全是模板」
    的书却显示 ready。入口层把空 content 也记为失败，据此降级（全失败→error，部分
    失败→partial），不让它冒充正常成书。

    min_tokens / extra_kwargs 只给生产 caller 用（见 min_output_tokens）。
    """

    def __init__(self, raw: Callable[..., Awaitable[dict]], *, cap_usd: float, model: str,
                 min_tokens: int = 0, extra_kwargs: Optional[dict] = None):
        from omodul._base import CostTracker

        self.raw = raw
        self.cap_usd = cap_usd
        self.model = model
        self.tracker = CostTracker()
        self.exceeded = False
        self.min_tokens = min_tokens
        self.extra_kwargs = dict(extra_kwargs or {})
        self.ok_calls = 0
        self.failed_calls = 0

    async def __call__(self, *, messages: list[dict], system: Optional[str] = None,
                       max_tokens: int = 800) -> dict:
        if self.tracker.total_usd >= self.cap_usd:
            self.exceeded = True
            raise BookBudgetExceeded(
                f"单本编译开销已达上限 ${self.cap_usd:.2f}，停止后续生成"
            )
        try:
            async with llm_slot():
                resp = await self.raw(messages=messages, system=system,
                                      max_tokens=max(max_tokens, self.min_tokens),
                                      **self.extra_kwargs)
        except Exception:
            self.failed_calls += 1
            raise
        self.tracker.add_from_response(resp, model=self.model)
        if str(resp.get("content") or "").strip():
            self.ok_calls += 1
        else:
            self.failed_calls += 1
        return resp


async def _adopt_compiled_book(db: AsyncSession, *, placeholder_id: str, compiled_id: str,
                               status: str, error: Optional[str]) -> None:
    """把 omodul 编出来的书并入占位行（对外 book_id 不变），然后删掉 omodul 那一行。"""
    await db.execute(
        text("UPDATE book_chapters SET book_id = :ph WHERE book_id = :real"),
        {"ph": placeholder_id, "real": compiled_id},
    )
    await db.execute(
        text("""
        UPDATE books ph SET title = r.title, description = r.description, scope = r.scope,
               target_level = r.target_level, status = :status, fingerprint = r.fingerprint,
               cost_usd = r.cost_usd, decision_trail_path = r.decision_trail_path,
               report_path = r.report_path, error = :error, updated_at = now()
        FROM books r WHERE ph.id = :ph AND r.id = :real
    """),
        {"ph": placeholder_id, "real": compiled_id, "status": status, "error": error},
    )
    await db.execute(text("DELETE FROM books WHERE id = :real"), {"real": compiled_id})
    await db.commit()


SessionFactory = Callable[[], Any]


async def run_compile_job(
    book_id: str,
    *,
    session_factory: Optional[SessionFactory] = None,
    caller: Optional[Callable[..., Awaitable[dict]]] = None,
    out_root: Optional[Path] = None,
) -> dict:
    """Celery 任务体：queued → compiling → 调 omodul.book_compile → ready/partial/error。

    幂等：只认领 status=queued 的行（acks_late 重投时不会二次花钱）；例外是
    compiling 超过 STALE_AFTER_MINUTES 的残留（worker 中途被重启/杀掉），重投时重新认领。
    """
    from omodul.book_compile import BookCompileConfig, BookCompileInput, book_compile

    engine = None
    if session_factory is None:
        from obase.config import settings

        engine = create_async_engine(settings.DATABASE_URL)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession,
                                             expire_on_commit=False)
    try:
        async with session_factory() as db:
            claimed = (
                await db.execute(
                    text(f"""
                UPDATE books SET status = 'compiling', updated_at = now()
                WHERE id = :id AND (
                    status = 'queued'
                    OR (status = 'compiling'
                        AND updated_at <= now() - interval '{STALE_AFTER_MINUTES} minutes'))
                RETURNING textbook_id
            """),
                    {"id": book_id},
                )
            ).fetchone()
            await db.commit()
            if claimed is None:
                return {"status": "skipped", "book_id": book_id,
                        "reason": "not queued (already running/finished or missing)"}
            textbook_id = claimed.textbook_id

            try:
                min_tokens, extra = 0, {}
                if caller is None:
                    from services.providers.setup import get_optional_text_caller

                    caller = get_optional_text_caller()
                    if caller is None:
                        await mark_error(db, book_id, "没有可用的 LLM provider（未配置或仅 mock）")
                        return {"status": "error", "book_id": book_id, "error": "no_llm"}
                    # 生产 caller：抬 max_tokens 下限 + 关思维链（推理模型回退时不至于空 content）
                    min_tokens, extra = min_output_tokens(), {"enable_thinking": False}

                config = BookCompileConfig(textbook_id=textbook_id,
                                           budget_usd=per_book_cost_cap_usd())
                budget = BudgetCaller(caller, cap_usd=per_book_cost_cap_usd(),
                                      model=config.llm_model, min_tokens=min_tokens,
                                      extra_kwargs=extra)
                out_dir = (out_root or output_root()) / book_id
                out_dir.mkdir(parents=True, exist_ok=True)

                result = await book_compile(
                    config, BookCompileInput(db=db, caller=budget), out_dir
                )
            except Exception as exc:  # noqa: BLE001 - 任务不能 crash worker
                _log.exception("book compile %s crashed", book_id)
                await db.rollback()
                await mark_error(db, book_id, f"{type(exc).__name__}: {exc}")
                return {"status": "error", "book_id": book_id, "error": str(exc)}

            cost = float(result.get("cost_usd") or budget.tracker.total_usd or 0.0)
            if result.get("status") != "completed" or not result.get("book_id"):
                await db.rollback()
                err = result.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                await mark_error(db, book_id, msg or "编译失败", cost_usd=cost)
                return {"status": "error", "book_id": book_id, "error": msg,
                        "cost_usd": cost}

            status = str(result.get("book_status") or "ready")
            error = None
            if budget.exceeded:
                status = "error"
                error = f"单本编译开销达到上限 ${budget.cap_usd:.2f}，部分内容未生成"
            elif budget.ok_calls == 0:
                status = "error"
                error = f"LLM 调用全部失败或返回空内容（{budget.failed_calls} 次），内容只是静态模板"
            elif budget.failed_calls and status == "ready":
                status = "partial"
                error = f"{budget.failed_calls} 次 LLM 调用失败或返回空内容，部分内容为静态模板"
            await _adopt_compiled_book(db, placeholder_id=book_id,
                                       compiled_id=str(result["book_id"]),
                                       status=status, error=error)
            return {
                "status": status,
                "book_id": book_id,
                "cost_usd": cost,
                "n_chapters": result.get("n_chapters"),
                "n_block_errors": result.get("n_block_errors"),
                "llm_calls_ok": budget.ok_calls,
                "llm_calls_failed": budget.failed_calls,
            }
    finally:
        if engine is not None:
            await engine.dispose()


__all__ = [
    "BookBudgetExceeded",
    "BudgetCaller",
    "CompileRejected",
    "create_compile_job",
    "enqueue_compile",
    "get_compile_status",
    "list_compilable_textbooks",
    "llm_concurrency",
    "llm_slot",
    "mark_error",
    "per_user_daily_limit",
    "run_compile_job",
]

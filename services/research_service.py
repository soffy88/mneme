"""研究报告（DeepTutor「Deep Research」的儿童安全版，layer-4 service）。

学生提一个主题问题 → 只在本地 Knowledge Hub（教材切片）里检索 → 生成一份简短的
结构化报告，**每一条论断都引用 书/页/切片**；找不到依据的论断明确标「教材中没有
找到依据」，不编造。不联网、不做 web 搜索。

设计要点（红线 / 防幻觉）：

1. **只引用检索到的切片**：给 LLM 的来源编号 S1..Sn 只来自本次
   ``knowledge_hub_search.search_knowledge_base`` 的结果；LLM 返回后逐条校验，
   引用了不存在编号的论断被剥掉引用，没有任何有效引用的论断被移进
   ``unsupported``（标注「教材中没有找到依据」），不作为事实展示。
2. **检索为空就不生成**：没有任何相关切片时直接返回 ``no_sources``，**不调用 LLM**
   （没有素材就没有回答，杜绝凭空作答）。
3. **LLM 不可用时降级为摘录**：直接摘出检索到的原文句子并逐条标出处，状态
   ``extractive``——仍然只有教材原文，没有生成内容。
4. **不进门控**：本模块不 import 任何门控/判分/掌握度模块；研究记录不写证据、不改
   掌握度/FSRS（``tests/test_research.py`` AST 静态断言）。persona 只影响语气。
5. **限额与成本**：每人每天 ``MNEME_RESEARCH_DAILY_LIMIT``（默认 10，admin 豁免）；
   全站每天 ``MNEME_RESEARCH_DAILY_USD``（默认 2 USD，按名义单价估算）；单次输出
   ``MNEME_RESEARCH_MAX_TOKENS``（默认 1500）+ 来源上下文长度上限。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

ID_PREFIX = "rsr_"
MAX_QUESTION_CHARS = 200
UNSUPPORTED_NOTE = "教材中没有找到依据"
NO_SOURCE_MESSAGE = (
    "本地教材库里没有找到和这个问题相关的内容，所以我不做推测回答。"
    "可以换个说法再问，或者问问老师。"
)

# 儿童安全：明显越界的问题直接拒绝（不检索、不调用 LLM、不计入限额）。
_BLOCKED_PATTERNS = (
    "自杀", "自残", "炸药", "制毒", "毒品", "枪支", "色情", "赌博",
    "suicide", "porn", "bomb",
)


class ResearchRejected(Exception):
    """校验/限额拒绝：status_code 直接映射成 HTTP 状态。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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
    return max(0, _env_int("MNEME_RESEARCH_DAILY_LIMIT", 10))


def global_daily_cost_cap_usd() -> float:
    return max(0.0, _env_float("MNEME_RESEARCH_DAILY_USD", 2.0))


def max_output_tokens() -> int:
    return max(200, min(_env_int("MNEME_RESEARCH_MAX_TOKENS", 1500), 4000))


def top_k() -> int:
    return max(1, min(_env_int("MNEME_RESEARCH_TOP_K", 6), 10))


def llm_timeout_seconds() -> float:
    return max(10.0, min(_env_float("MNEME_RESEARCH_LLM_TIMEOUT_SECONDS", 120.0), 240.0))


# 名义单价（与 omodul CostTracker 的 Sonnet 量级一致，宁高勿低）：只用于止损，不是账单。
def _estimate_cost(usage: dict) -> float:
    inp = int(usage.get("input_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    return round(inp / 1000 * 0.003 + out / 1000 * 0.015, 6)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(now: datetime) -> datetime:
    # 「今天」按北京时间算（产品面向中国中小学生）。
    cst = timezone(timedelta(hours=8))
    local = now.astimezone(cst)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ── 检索 ────────────────────────────────────────────────────────────────────

_SNIPPET_CHARS = 700


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# 问句里的功能词/泛化词：切掉它们剩下的最长片段通常就是主题词（「勾股定理」「牛顿第二定律」）。
_QUESTION_SPLIT = re.compile(
    r"[，。？！?!、,\s]|的|在|是|哪些|什么|怎么|怎样|如何|为什么|为何|吗|呢|"
    r"例子|举例|方法|证明|应用|生活|区别|介绍|讲解|解释|理解"
)


def topic_queries(question: str, *, max_extra: int = 1) -> list[str]:
    """原问题 + 主题词子查询。

    词面检索（embedding 不可用时的兜底）对长问句只命中寥寥一两条（2026-10-11 实测
    「勾股定理的证明方法」只回 1 条，而「勾股定理」回 6 条），所以补一个主题词查询
    扩大候选面；原问题的结果始终排在前面。
    """
    q = _clean(question)
    parts = sorted({p for p in _QUESTION_SPLIT.split(q) if p and len(p) >= 3},
                   key=lambda p: (-len(p), q.find(p)))
    extra = [p for p in parts if p != q][:max_extra]
    return [q, *extra]


async def retrieve_sources(db: AsyncSession, question: str, *, k: int | None = None) -> list[dict]:
    """检索本地教材切片 → 编号来源 S1..Sn（只取有内容、分数>0 的切片，去重）。

    原问题的命中在前，主题词子查询的命中补在后面，总数不超过 k。
    """
    from services.knowledge_hub_search import search_knowledge_base

    limit = k or top_k()
    hits: list[dict] = []
    for sub in topic_queries(question):
        result = await search_knowledge_base(db, query=sub, top_k=limit, min_score=0.0)
        hits.extend(result.get("results") or [])
    sources: list[dict] = []
    seen: set[str] = set()
    for r in hits:
        if len(sources) >= limit:
            break
        content = _clean(str(r.get("content") or ""))
        cid = str(r.get("chunk_id") or "")
        if not content or not cid or cid in seen or float(r.get("score") or 0) <= 0:
            continue
        seen.add(cid)
        meta = r.get("textbook_meta") or {}
        sources.append({
            "id": f"S{len(sources) + 1}",
            "chunk_id": cid,
            "pdf_id": r.get("pdf_id"),
            "book_name": meta.get("book_name"),
            "subject": meta.get("subject"),
            "grade": meta.get("grade"),
            "page_number": r.get("page_number"),
            "score": r.get("score"),
            "verified": bool(r.get("verified")),
            "excerpt": content[:_SNIPPET_CHARS],
        })
    return sources


# ── 生成 + 校验 ─────────────────────────────────────────────────────────────


def _grade_hint(grade: Optional[str]) -> str:
    if not grade:
        return "中小学生"
    return f"{grade} 年级段的学生"


def build_prompt(question: str, sources: list[dict], *, grade: Optional[str],
                 persona_block: Optional[str]) -> tuple[str, str]:
    """返回 (system, user)。来源原文放进 user，要求严格 JSON。"""
    system_parts = [
        "你是面向中国中小学生的学习助手，正在写一份简短的『教材研究报告』。",
        f"读者是{_grade_hint(grade)}：用他们能懂的词，句子简短，语气友好。",
        "硬性规则：",
        "1. 只能使用下面给出的教材来源 S1..Sn 中的内容，不得使用来源以外的知识。",
        "2. 每一条要点都必须在 sources 里写出支撑它的来源编号（如 [\"S1\"]）。",
        "3. 如果某个方面教材来源里没有依据，不要编造，把它写进 gaps。",
        "4. 不讨论与学习无关或不适合未成年人的内容。",
        "5. 只输出一个 JSON 对象，不要输出其它文字。",
    ]
    if persona_block:
        system_parts.append("\n" + persona_block + "\n（人格只影响语气，不改变上面的规则。）")
    src_lines = []
    for s in sources:
        where = f"《{s.get('book_name') or '教材'}》"
        if s.get("page_number") is not None:
            where += f" 第{s['page_number']}页"
        src_lines.append(f"[{s['id']}] {where}\n{s['excerpt']}")
    schema = (
        '{"title": "报告标题", '
        '"summary": {"text": "两三句话的总结", "sources": ["S1"]}, '
        '"sections": [{"heading": "小标题", "points": [{"text": "一条要点", "sources": ["S1", "S2"]}]}], '
        '"gaps": ["教材里没有讲到的方面"]}'
    )
    user = (
        f"问题：{question}\n\n教材来源：\n" + "\n\n".join(src_lines)
        + f"\n\n请按这个 JSON 结构输出（2~4 个小节，每节 1~4 条要点）：\n{schema}"
    )
    return "\n".join(system_parts), user


def _extract_json(raw: str) -> Any:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def _bigrams(s: str) -> set[str]:
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", s.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _support(text_: str, cited: list[dict]) -> str:
    """词面支撑度（只作提示，不作过滤）：论断与所引切片共享的二元组比例。"""
    claim = _bigrams(text_)
    if not claim:
        return "weak"
    pool: set[str] = set()
    for s in cited:
        pool |= _bigrams(s.get("excerpt") or "")
    ratio = len(claim & pool) / len(claim)
    return "matched" if ratio >= 0.2 else "weak"


def validate_report(raw: Any, sources: list[dict]) -> dict:
    """把 LLM 输出收敛成只引用检索切片的报告。

    - 引用里不在 S1..Sn 的编号一律剔除；
    - 剔除后没有有效引用的要点 → 移入 unsupported（标「教材中没有找到依据」）；
    - 每条保留下来的要点附上完整出处（书/页/chunk_id）。
    """
    by_id = {s["id"]: s for s in sources}
    unsupported: list[dict] = []
    dropped_refs: list[str] = []

    def clean_point(p: Any) -> Optional[dict]:
        if isinstance(p, str):
            p = {"text": p, "sources": []}
        if not isinstance(p, dict):
            return None
        txt = _clean(str(p.get("text") or ""))[:600]
        if not txt:
            return None
        refs_raw = p.get("sources") or []
        if isinstance(refs_raw, str):
            refs_raw = [refs_raw]
        refs: list[str] = []
        for ref in refs_raw:
            ref_s = str(ref).strip().strip("[]")
            if ref_s in by_id and ref_s not in refs:
                refs.append(ref_s)
            elif ref_s:
                dropped_refs.append(ref_s)
        if not refs:
            unsupported.append({"text": txt, "note": UNSUPPORTED_NOTE})
            return None
        cited = [by_id[r] for r in refs]
        return {
            "text": txt,
            "sources": refs,
            "citations": [_citation(s) for s in cited],
            "support": _support(txt, cited),
        }

    data = raw if isinstance(raw, dict) else {}
    summary = clean_point(data.get("summary")) if data.get("summary") else None
    sections: list[dict] = []
    for sec in (data.get("sections") or [])[:6]:
        if not isinstance(sec, dict):
            continue
        points = [cp for cp in (clean_point(p) for p in (sec.get("points") or [])[:6]) if cp]
        if points:
            sections.append({"heading": _clean(str(sec.get("heading") or ""))[:80] or "要点",
                             "points": points})
    gaps = [_clean(str(g))[:200] for g in (data.get("gaps") or []) if _clean(str(g))][:6]
    return {
        "title": _clean(str(data.get("title") or ""))[:80] or "研究报告",
        "summary": summary,
        "sections": sections,
        "unsupported": unsupported,
        "gaps": gaps,
        "dropped_refs": sorted(set(dropped_refs)),
    }


def _citation(s: dict) -> dict:
    return {
        "source_id": s["id"],
        "book_name": s.get("book_name"),
        "page_number": s.get("page_number"),
        "chunk_id": s["chunk_id"],
        "verified": s.get("verified", False),
    }


_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def extractive_report(question: str, sources: list[dict]) -> dict:
    """LLM 不可用时：只摘教材原文句子，逐条标出处（无生成内容）。"""
    points = []
    for s in sources[:4]:
        sents = [x.strip() for x in _SENT_SPLIT.split(s["excerpt"]) if len(x.strip()) >= 8]
        snippet = "".join(sents[:2])[:220] or s["excerpt"][:220]
        points.append({"text": snippet, "sources": [s["id"]], "citations": [_citation(s)],
                       "support": "matched"})
    return {
        "title": f"教材摘录：{question[:40]}",
        "summary": None,
        "sections": [{"heading": "教材原文摘录", "points": points}] if points else [],
        "unsupported": [],
        "gaps": ["AI 讲解暂时不可用，下面是教材原文摘录。"],
        "dropped_refs": [],
    }


async def _persona_block(db: AsyncSession, slug: Optional[str]) -> Optional[str]:
    try:
        from services import persona_store

        persona = await persona_store.get_persona(db, slug or persona_store.DEFAULT_PERSONA_SLUG)
        return persona_store.render_for_prompt(persona) if persona else None
    except Exception:  # noqa: BLE001 - persona 只是语气，缺了不影响报告
        return None


async def generate_report(
    db: AsyncSession,
    question: str,
    *,
    grade: Optional[str] = None,
    persona_slug: Optional[str] = None,
    caller: Any = None,
    sources: Optional[list[dict]] = None,
) -> dict:
    """纯生成（不写库）：检索 → （LLM）→ 校验。返回 {status, report, sources, usage, model, ...}。"""
    started = time.monotonic()
    if sources is None:
        sources = await retrieve_sources(db, question)
    if not sources:
        return {
            "status": "no_sources",
            "report": {"title": "没有找到教材依据", "summary": None, "sections": [],
                       "unsupported": [], "gaps": [NO_SOURCE_MESSAGE], "dropped_refs": []},
            "sources": [], "usage": {}, "model": None, "cost_usd": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000), "error": None,
        }

    if caller is None:
        from services.providers.setup import get_optional_text_caller

        caller = get_optional_text_caller()
    if caller is None:
        return {
            "status": "extractive", "report": extractive_report(question, sources),
            "sources": sources, "usage": {}, "model": None, "cost_usd": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000), "error": "no_llm",
        }

    system, user = build_prompt(question, sources, grade=grade,
                                persona_block=await _persona_block(db, persona_slug))
    error: Optional[str] = None
    usage: dict = {}
    try:
        resp = await asyncio.wait_for(
            caller(messages=[{"role": "user", "content": user}], system=system,
                   max_tokens=max_output_tokens()),
            timeout=llm_timeout_seconds(),
        )
        usage = dict(resp.get("usage") or {})
        report = validate_report(_extract_json(str(resp.get("content") or "")), sources)
        if not report["sections"] and not report["summary"]:
            raise ValueError("report has no supported claims")
        status = "ready"
    except Exception as exc:  # noqa: BLE001 - 降级为原文摘录，绝不编造
        error = f"{type(exc).__name__}"[:120]
        _log.warning("research: LLM path failed (%s), falling back to extractive", error)
        report = extractive_report(question, sources)
        status = "extractive"
    model = getattr(caller, "last_good_model", None) or getattr(caller, "model", None)
    return {
        "status": status, "report": report, "sources": sources, "usage": usage,
        "model": str(model) if model else None, "cost_usd": _estimate_cost(usage),
        "latency_ms": int((time.monotonic() - started) * 1000), "error": error,
    }


# ── 持久化 + 限额 ───────────────────────────────────────────────────────────


def _blocked(question: str) -> bool:
    low = question.lower()
    return any(p in low for p in _BLOCKED_PATTERNS)


async def _check_limits(db: AsyncSession, student_id: str, *, is_admin: bool) -> None:
    start = _day_start(_now())
    if not is_admin:
        used = (await db.execute(
            text("SELECT count(*) FROM research_reports WHERE student_id=:s AND created_at >= :d"),
            {"s": student_id, "d": start},
        )).scalar_one()
        if int(used) >= per_user_daily_limit():
            raise ResearchRejected(429, f"今天的研究次数已用完（每天 {per_user_daily_limit()} 次），明天再来吧")
    spent = (await db.execute(
        text("SELECT coalesce(sum(cost_usd), 0) FROM research_reports WHERE created_at >= :d"),
        {"d": start},
    )).scalar_one()
    if float(spent) >= global_daily_cost_cap_usd():
        raise ResearchRejected(503, "今天的研究服务额度已用完，请明天再试")


async def create_research(
    db: AsyncSession,
    *,
    student_id: str,
    question: str,
    grade: Optional[str] = None,
    persona_slug: Optional[str] = None,
    is_admin: bool = False,
    caller: Any = None,
) -> dict:
    q = _clean(question)
    if not q:
        raise ResearchRejected(422, "问题不能为空")
    if len(q) > MAX_QUESTION_CHARS:
        raise ResearchRejected(422, f"问题太长了（最多 {MAX_QUESTION_CHARS} 字）")
    if _blocked(q):
        raise ResearchRejected(422, "这个问题不适合在这里研究，换一个学习相关的问题吧")
    await _check_limits(db, student_id, is_admin=is_admin)

    result = await generate_report(db, q, grade=grade, persona_slug=persona_slug, caller=caller)
    rid = ID_PREFIX + uuid.uuid4().hex[:16]
    await db.execute(
        text(
            "INSERT INTO research_reports (id, student_id, question, grade, persona_slug, status, "
            "report, sources, model, input_tokens, output_tokens, cost_usd, latency_ms, error, "
            "created_at) VALUES (:id, :s, :q, :g, :p, :st, CAST(:r AS jsonb), CAST(:src AS jsonb), "
            ":m, :it, :ot, :c, :lat, :e, :ts)"
        ),
        {
            "id": rid, "s": student_id, "q": q, "g": grade, "p": persona_slug,
            "st": result["status"],
            "r": json.dumps(result["report"], ensure_ascii=False),
            "src": json.dumps(result["sources"], ensure_ascii=False),
            "m": result["model"],
            "it": int(result["usage"].get("input_tokens", 0) or 0),
            "ot": int(result["usage"].get("output_tokens", 0) or 0),
            "c": float(result["cost_usd"]), "lat": int(result["latency_ms"]),
            "e": result["error"], "ts": _now(),
        },
    )
    await db.commit()
    got = await get_research(db, rid, student_id=student_id)
    assert got is not None
    return got


def _json(v: Any) -> Any:
    # text() 查询下 asyncpg 把 jsonb 原样回成 str
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except (TypeError, json.JSONDecodeError):
            return None
    return v


def _row(r: Any, *, full: bool) -> dict:
    report = _json(r.report) or {}
    out = {
        "id": r.id, "question": r.question, "grade": r.grade, "status": r.status,
        "title": report.get("title") if isinstance(report, dict) else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if full:
        out.update({
            "persona_slug": r.persona_slug, "report": report, "sources": _json(r.sources) or [],
            "model": r.model, "latency_ms": r.latency_ms,
            "usage": {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens},
            "error": r.error,
        })
    return out


async def get_research(db: AsyncSession, research_id: str, *, student_id: str) -> Optional[dict]:
    """只返回本人的记录（别人的 id 一律当不存在）。"""
    r = (await db.execute(
        text("SELECT * FROM research_reports WHERE id=:id AND student_id=:s"),
        {"id": research_id, "s": student_id},
    )).first()
    return _row(r, full=True) if r else None


async def list_research(db: AsyncSession, *, student_id: str, limit: int = 20) -> dict:
    rows = (await db.execute(
        text("SELECT id, question, grade, status, report, created_at FROM research_reports "
             "WHERE student_id=:s ORDER BY created_at DESC LIMIT :n"),
        {"s": student_id, "n": max(1, min(limit, 100))},
    )).fetchall()
    start = _day_start(_now())
    used = sum(1 for r in rows if r.created_at and r.created_at >= start)
    if len(rows) >= limit:  # 列表被截断时精确计数
        used = int((await db.execute(
            text("SELECT count(*) FROM research_reports WHERE student_id=:s AND created_at >= :d"),
            {"s": student_id, "d": start},
        )).scalar_one())
    return {
        "items": [_row(r, full=False) for r in rows],
        "daily_limit": per_user_daily_limit(),
        "used_today": used,
    }


__all__ = [
    "NO_SOURCE_MESSAGE",
    "ResearchRejected",
    "UNSUPPORTED_NOTE",
    "build_prompt",
    "create_research",
    "extractive_report",
    "generate_report",
    "get_research",
    "list_research",
    "per_user_daily_limit",
    "retrieve_sources",
    "topic_queries",
    "validate_report",
]

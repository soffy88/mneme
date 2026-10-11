#!/usr/bin/env python3
"""Chemistry / biology textbook PDFs -> knowledge_clusters + knowledge_units.

Same shape as scripts/extract_physics_ku_batch.py (KC = LLM cluster, KU id
``{tb_id}-ku-{slug}``, insert-only ON CONFLICT DO NOTHING), but the LLM is the
production text caller (``services.providers.setup.get_text_caller`` -> Veya,
``veya-free`` first) instead of a direct DeepSeek key, and calls are sequential
with a pause between them to keep cost/load small.

Runs inside the api container (it carries the VEYA_* env and the DB url):

    docker exec mneme-api-1 python scripts/extract_science_ku_batch.py --dry-run --limit 1
    docker exec mneme-api-1 python scripts/extract_science_ku_batch.py --books RENJIAO-G9-CHEMISTRY-S

Textbook rows must already exist (scripts/ingest_curriculum_textbooks.py
creates them). Books that already have KUs are skipped unless --resume is
given (then only segments whose KUs are missing are inserted, via ON CONFLICT).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("MNEME_ROOT") or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

PDF_DIR = ROOT / "curriculum_standards"
SEGMENT_CHARS = int(os.environ.get("KU_SEGMENT_CHARS", "9000"))
MIN_SEGMENT_CHARS = 2500
LLM_TIMEOUT_S = float(os.environ.get("KU_LLM_TIMEOUT_S", "240"))
_M22 = "（根据2022年版课程标准修订）义务教育教科书"

CATALOG: list[dict[str, str]] = [
    {"tb_id": "RENJIAO-G9-CHEMISTRY-S", "subject": "chemistry",
     "filename": f"M_化学_{_M22}·化学九年级上册.pdf", "title": "人教版化学九年级上册"},
    {"tb_id": "RENJIAO-G9-CHEMISTRY-X", "subject": "chemistry",
     "filename": "M_化学_(根据2022年版课程标准修订)义务教育教科书·化学九年级下册.pdf",
     "title": "人教版化学九年级下册"},
    {"tb_id": "RENJIAO-G10-CHEMISTRY-BX1", "subject": "chemistry",
     "filename": "H_化学_普通高中教科书·化学必修第一册.pdf", "title": "人教版高中化学必修第一册"},
    {"tb_id": "RENJIAO-G10-CHEMISTRY-BX2", "subject": "chemistry",
     "filename": "H_化学_普通高中教科书·化学必修第二册.pdf", "title": "人教版高中化学必修第二册"},
    {"tb_id": "RENJIAO-G7-BIOLOGY-S", "subject": "biology",
     "filename": f"M_生物学_{_M22}·生物学七年级上册.pdf", "title": "人教版生物学七年级上册"},
    {"tb_id": "RENJIAO-G7-BIOLOGY-X", "subject": "biology",
     "filename": f"M_生物学_{_M22}·生物学七年级下册.pdf", "title": "人教版生物学七年级下册"},
    {"tb_id": "RENJIAO-G8-BIOLOGY-S", "subject": "biology",
     "filename": f"M_生物学_{_M22}·生物学八年级上册.pdf", "title": "人教版生物学八年级上册"},
    {"tb_id": "RENJIAO-G8-BIOLOGY-X", "subject": "biology",
     "filename": f"M_生物学_{_M22}·生物学八年级下册.pdf", "title": "人教版生物学八年级下册"},
    {"tb_id": "RENJIAO-G10-BIOLOGY-BX1", "subject": "biology",
     "filename": "H_生物学_普通高中教科书·生物学必修1分子与细胞.pdf",
     "title": "人教版高中生物学必修1·分子与细胞"},
    {"tb_id": "RENJIAO-G10-BIOLOGY-BX2", "subject": "biology",
     "filename": "H_生物学_普通高中教科书·生物学必修2遗传与进化.pdf",
     "title": "人教版高中生物学必修2·遗传与进化"},
]

KU_TYPES: dict[str, dict[str, str]] = {
    "chemistry": {
        "concept": "化学概念——定义一个化学术语或物质类别（元素、化合物、氧化还原反应、物质的量）",
        "substance": "物质及其性质——一种具体物质/一类物质的组成、性质、用途（氧气的性质、碳酸钠、铁的化合物）",
        "reaction": "化学反应——一个具体反应或一类反应及其化学方程式（实验室制氧气、酸碱中和反应）",
        "principle": "化学规律/原理——普遍规律或定律（质量守恒定律、元素周期律、化学平衡移动）",
        "experiment": "实验探究——一个完整的实验或实验操作（粗盐提纯、配制一定物质的量浓度的溶液）",
        "method": "方法与计算——通用思维方法或计算方法（控制变量法、根据化学方程式计算、模型认知）",
    },
    "biology": {
        "concept": "生物学概念——定义一个术语（细胞、生态系统、基因、等位基因）",
        "structure": "结构与功能——一个结构及其功能（细胞膜的结构、叶绿体、神经元、DNA双螺旋）",
        "process": "生命过程——一个动态的生理/生命过程（光合作用、细胞呼吸、有丝分裂、减数分裂）",
        "principle": "规律/原理——普遍规律或学说（分离定律、自由组合定律、细胞学说、自然选择）",
        "experiment": "实验探究——一个完整的实验或观察活动（观察根尖分生区有丝分裂、检测生物组织中的糖类）",
        "method": "科学方法——通用科学思维方法（假说—演绎法、同位素标记法、模型构建、控制变量）",
    },
}
SUBJECT_ZH = {"chemistry": "化学", "biology": "生物学"}


def system_prompt(subject: str) -> str:
    types = "\n".join(f"  {k:<11}{v}" for k, v in KU_TYPES[subject].items())
    zh = SUBJECT_ZH[subject]
    return f"""你是中国K12{zh}教材知识点（KU）提取专家。

KU（知识单元）定义：教材正文中一个最小可独立掌握/遗忘的知识项。

▌{zh} KU 类型（ku_type 必须精确选一）：
{types}

▌每个 KU 的字段：
  name           KU 名称（≤25字，精确表达，用教材术语）
  ku_type        上面类型之一
  core           核心定义/规律/过程要点（≤100字，可含化学方程式或关键数据）
  difficulty     0.1–0.9（0.1=识记，0.5=理解应用，0.9=综合应用）
  prerequisites  前置KU名列表（最多4个）

▌KC（知识簇）：按教材逻辑聚类（通常对应一节/一个课题），每 KC 含 2–8 个 KU。

▌规则：
  - 只提取正文知识；忽略目录、版权页、习题答案格式、插图说明
  - 实验必须独立成 KU（ku_type=experiment）
  - 不设数量限制，内容多 KU 多

输出纯 JSON（无 markdown 代码块）：
{{"kus":[{{"id":"ku-001","name":"…","ku_type":"concept","core":"…","difficulty":0.4,"prerequisites":[]}}],
 "kcs":[{{"id":"kc-001","name":"KC名","ku_ids":["ku-001"]}}]}}
只输出 JSON，不加任何其他文字。"""


# ── PDF -> segments ──────────────────────────────────────────────────────────

_HEAD_RE = re.compile(r"第\s*([一二三四五六七八九十0-9]+)\s*(章|单元)\s*([^\n.…·]{0,20})")


def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if len(t) >= 80 and t.count("…") < 20 and t.count("·") < 40 and t.count("....") < 5:  # drop TOC/blank pages
            pages[i + 1] = t
    doc.close()
    return pages


def split_segments(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Consecutive page runs of <= SEGMENT_CHARS; start a new run when a new
    第X章/单元 heading first appears at a page top (and the run is not tiny)."""
    segs: list[dict[str, Any]] = []
    cur: dict[str, Any] = {"heading": "", "pages": [], "text": ""}
    seen: set[str] = set()
    heading = ""
    for pg in sorted(pages):
        t = pages[pg]
        m = _HEAD_RE.search(t[:200])
        new_heading = False
        if m:
            key = f"第{m.group(1)}{m.group(2)}"
            if key not in seen:
                seen.add(key)
                heading = (key + " " + m.group(3).strip()).strip()
                new_heading = True
        if cur["pages"] and (
            (new_heading and len(cur["text"]) >= MIN_SEGMENT_CHARS)
            or len(cur["text"]) + len(t) > SEGMENT_CHARS
        ):
            segs.append(cur)
            cur = {"heading": heading, "pages": [], "text": ""}
        if not cur["heading"]:
            cur["heading"] = heading
        cur["pages"].append(pg)
        cur["text"] += f"\n[p{pg}]\n{t}"
    if cur["pages"]:
        segs.append(cur)
    return segs


# ── LLM ──────────────────────────────────────────────────────────────────────


def _parse_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object ({len(raw)} chars): {raw[:120]!r}")
    obj = json.loads(m.group())
    if not isinstance(obj, dict) or not isinstance(obj.get("kus"), list):
        raise ValueError("JSON lacks kus[]")
    return obj


async def llm_extract(caller: Any, subject: str, seg: dict[str, Any], hint: str) -> tuple[dict[str, Any], str]:
    user = (
        f"{SUBJECT_ZH[subject]}教材 {seg['heading'] or ''}{hint} 正文（第{seg['pages'][0]}–{seg['pages'][-1]}页，"
        f"{len(seg['text'])}字符，[pN] 为页码标记）：\n\n{seg['text']}\n\n"
        "请提取本段全部 KU，聚成 KC，标前置依赖。"
    )
    last: Exception | None = None
    for attempt in range(2):
        try:
            out = await asyncio.wait_for(
                caller(
                    messages=[{"role": "user", "content": user}],
                    system=system_prompt(subject),
                    max_tokens=8000,
                    enable_thinking=False,
                ),
                timeout=LLM_TIMEOUT_S,
            )
            model = str(getattr(caller, "last_good_model", "") or out.get("model") or "")
            return _parse_json(str(out.get("content") or "")), model
        except Exception as e:  # noqa: BLE001 - retry once, then report
            last = e
            print(f"    [LLM fail {attempt + 1}] {str(e)[:160]}", flush=True)
            await asyncio.sleep(5)
    raise RuntimeError(f"LLM failed twice: {last}")


# ── DB (insert-only) ─────────────────────────────────────────────────────────


def _slug(s: str) -> str:
    return re.sub(r"[^\w一-鿿]", "-", s)[:40].strip("-").lower()


async def store(db: Any, book: dict[str, str], kus: list[dict[str, Any]], kc_order: dict[str, int]) -> int:
    from sqlalchemy import text as sa_text

    tb_id = book["tb_id"]
    valid = KU_TYPES[book["subject"]]
    n = 0
    for ku in kus:
        kc_name = (ku.get("_kc") or "综合知识")[:100]
        if kc_name not in kc_order:
            kc_order[kc_name] = len(kc_order) + 1
        kc_id = f"{tb_id}-kc-{_slug(kc_name)}"[:80]
        await db.execute(
            sa_text(
                "INSERT INTO knowledge_clusters (id, textbook_id, name, display_order)"
                " VALUES (:id, :tb, :n, :o) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": kc_id, "tb": tb_id, "n": kc_name, "o": kc_order[kc_name]},
        )
        name = str(ku.get("name") or "").strip()[:200]
        if not name:
            continue
        kt = str(ku.get("ku_type") or "concept")
        try:
            diff = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
        except (TypeError, ValueError):
            diff = 0.5
        prereqs = [str(p) for p in (ku.get("prerequisites") or []) if p][:4]
        res = await db.execute(
            sa_text(
                "INSERT INTO knowledge_units (id, textbook_id, cluster_id, name, description,"
                " prerequisites, related_kus, difficulty, exam_frequency, question_types,"
                " ku_type, mastery_levels, provenance, ai_generated, verified)"
                " VALUES (:id, :tb, :kc, :n, :d, CAST(:pre AS jsonb), '[]'::jsonb, :diff, 'mid',"
                " '[]'::jsonb, :kt, '[]'::jsonb, CAST(:prov AS jsonb), true, false)"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": f"{tb_id}-ku-{_slug(name)}"[:100],
                "tb": tb_id,
                "kc": kc_id,
                "n": name,
                "d": str(ku.get("core") or "") or None,
                "pre": json.dumps(prereqs, ensure_ascii=False),
                "diff": diff,
                "kt": kt if kt in valid else "concept",
                "prov": json.dumps(ku["_prov"], ensure_ascii=False),
            },
        )
        n += res.rowcount or 0
    await db.commit()
    return n


# ── main ─────────────────────────────────────────────────────────────────────


async def process_book(book: dict[str, str], caller: Any, *, dry_run: bool, limit: int | None,
                       resume: bool, pause: float) -> str:
    from sqlalchemy import text as sa_text

    from obase.db import SessionLocal

    pdf = PDF_DIR / book["filename"]
    if not pdf.is_file():
        return "missing_pdf"
    async with SessionLocal() as db:
        if (await db.execute(sa_text("SELECT 1 FROM textbooks WHERE id=:id"), {"id": book["tb_id"]})).fetchone() is None:
            return "missing_textbook_row"
        have = (await db.execute(sa_text("SELECT count(*) FROM knowledge_units WHERE textbook_id=:id"),
                                 {"id": book["tb_id"]})).scalar() or 0
        if have and not resume:
            return f"skip_has_kus={have}"
        pages = extract_page_texts(pdf)
        segs = split_segments(pages)
        if limit:
            segs = segs[:limit]
        print(f"\n=== {book['title']} [{book['tb_id']}] pages={len(pages)} segments={len(segs)}", flush=True)
        kc_order: dict[str, int] = {}
        seen: set[str] = set()
        types: Counter[str] = Counter()
        inserted = extracted = 0
        for i, seg in enumerate(segs, 1):
            hint = f"（段{i}/{len(segs)}）"
            t0 = time.time()
            try:
                data, model = await llm_extract(caller, book["subject"], seg, hint)
            except Exception as e:  # noqa: BLE001
                print(f"  seg {i}: SKIPPED ({str(e)[:120]})", flush=True)
                continue
            kus = data.get("kus") or []
            ku_kc: dict[str, str] = {}
            for kc in data.get("kcs") or []:
                for kid in kc.get("ku_ids") or []:
                    ku_kc.setdefault(str(kid), str(kc.get("name") or ""))
            id2name = {str(k.get("id")): str(k.get("name") or "") for k in kus}
            fresh = []
            for ku in kus:
                name = str(ku.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                ku["_kc"] = ku_kc.get(str(ku.get("id")), "") or seg["heading"] or "综合知识"
                ku["prerequisites"] = [id2name.get(str(p), str(p)) for p in (ku.get("prerequisites") or [])]
                ku["_prov"] = {
                    "source": "smartedu_pdf",
                    "pdf": book["filename"],
                    "pages": [seg["pages"][0], seg["pages"][-1]],
                    "heading": seg["heading"],
                    "extractor": "scripts/extract_science_ku_batch.py",
                    "llm": model or "default_text_caller",
                }
                types[str(ku.get("ku_type"))] += 1
                fresh.append(ku)
            extracted += len(fresh)
            n = 0 if dry_run else await store(db, book, fresh, kc_order)
            inserted += n
            print(f"  seg {i}/{len(segs)} p{seg['pages'][0]}-{seg['pages'][-1]} {seg['heading'][:20]!r}: "
                  f"{len(fresh)} KU (+{n}) {time.time() - t0:.0f}s model={model}", flush=True)
            await asyncio.sleep(pause)
        print(f"  types: {dict(types)}", flush=True)
    return f"extracted={extracted} inserted={inserted} kcs={len(kc_order)}"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--books", action="append", help="textbook ids (default: all present)")
    ap.add_argument("--subjects", nargs="*", help="chemistry biology")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="segments per book (debug)")
    ap.add_argument("--resume", action="store_true", help="run even if the book already has KUs")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between LLM calls")
    args = ap.parse_args()

    from services.providers.setup import get_text_caller

    caller = get_text_caller()
    books = [b for b in CATALOG
             if (not args.books or b["tb_id"] in args.books)
             and (not args.subjects or b["subject"] in args.subjects)]
    for b in books:
        t0 = time.time()
        status = await process_book(b, caller, dry_run=args.dry_run, limit=args.limit,
                                    resume=args.resume, pause=args.pause)
        print(f"RESULT\t{b['tb_id']}\t{status}\t{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

#!/usr/bin/env python3
"""
物理 KU 本地 7B/9B 模型提取（对比 DeepSeek 质量用）。

用法：
  .venv/bin/python scripts/extract_physics_ku_local.py \\
    [--model qwen2.5:7b|qwen3.5:9b] \\
    [--dry-run] [--limit N] [--out FILE]

默认 --dry-run，输出到 scripts/physics_bx2_local_7b.json。
加 --no-dry-run 才入库。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("缺少 pymupdf: pip install pymupdf")
try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg: pip install asyncpg")
try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR  = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
DB_URL   = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme")
OLLAMA   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
CHUNK    = 7_000   # 本地模型 context 较小，缩短至 7K

BOOK = {
    "tb_id":    "RENJIAO-G10-PHYSICS-BX2",
    "filename": "H_物理_普通高中教科书·物理必修第二册.pdf",
    "title":    "高中物理必修第二册",
    "grade":    "G10",
    "subject":  "physics",
    "edition":  "RENJIAO",
}

VALID_KU_TYPES = {
    "physical_concept", "physical_law", "physical_model",
    "experiment", "method", "formula",
}

# ── Prompt（与 DeepSeek 版完全相同）────────────────────────────────────────────

LLM_SYSTEM = """你是中国K12物理教材知识点（KU）提取专家。

KU（知识单元）定义：教材正文中一个最小可独立掌握/遗忘的知识项。

▌物理 KU 类型（ku_type 必须精确选一）：
  physical_concept  物理概念——定义一个物理量或物理现象
                    （位移、速度、加速度、力、质量、惯性）
  physical_law      物理规律/定律——描述物理量之间的规律性关系
                    （牛顿第一/二/三定律、自由落体规律、运动学方程组）
  physical_model    物理模型——简化现实的理想化模型或典型情景
                    （质点模型、匀变速直线运动、轻绳轻杆、斜面模型）
                    ★ 注意：这是物理解题核心，必须独立识别，不能归入 concept
  experiment        实验探究——一个完整的实验设计与操作
                    （打点计时器测速、探究小车运动规律、验证牛顿第二定律）
                    ★ 注意：教材中每个"实验"章节必须提取为独立 KU
  method            科学思维方法——通用分析方法/技巧
                    （控制变量法、图像法、极限思想、等效替代法、微元法）
  formula           单条计算公式——可独立记忆和使用的公式
                    （v=v₀+at, x=v₀t+½at², F=ma, 合力公式）
                    注：一组公式（运动学方程组）归 physical_law，单条归 formula

▌每个 KU 的字段：
  name           KU 名称（≤25字，精确表达）
  ku_type        上面6类之一（必须准确分类）
  core           核心定义/公式/规律描述（≤80字）
  applicable_conditions  适用条件或限制（物理特有难点，如"仅适用匀变速直线运动"
                         "忽略空气阻力"；无条件则写"无特殊限制"）
  difficulty     0.1–0.9（0.1=理解即可，0.5=需推导练习，0.9=综合应用难）
  prerequisites  前置KU名列表（本册内或跨册，最多4个）
  experiment_meta 仅当 ku_type=experiment 时填写：
    {"purpose":"实验目的","principle":"实验原理","instruments":"主要器材",
     "key_steps":"关键步骤要点","data_method":"数据处理方法"}
    其他类型此字段设为 null

▌KC（知识簇）聚类规则：
  按物理逻辑聚类，每 KC 含 3–8 个 KU，同一 KC 内 KU 相互关联

▌规则：
  - 不设数量限制：内容多 KU 多，内容少 KU 少，自然浮动
  - physical_model 和 experiment 必须独立识别，不能混入 concept
  - 适用条件（applicable_conditions）必须填写，是物理 KU 的核心属性
  - 公式变量恢复正常字符（如 狓→x, 犪→a）

输出纯 JSON（无 markdown 代码块，无注释，无 ```）：
{
  "chapter": "章节名",
  "kus": [
    {
      "id": "ku-001",
      "name": "KU名称",
      "ku_type": "physical_concept",
      "core": "核心定义（≤80字）",
      "applicable_conditions": "适用条件",
      "difficulty": 0.4,
      "prerequisites": [],
      "experiment_meta": null
    }
  ],
  "kcs": [
    {"id": "kc-001", "name": "KC名", "logic_reason": "聚类逻辑", "ku_ids": ["ku-001"]}
  ]
}
只输出JSON，绝对不加任何其他文字、解释或markdown。"""


# ── PDF → 章节 ───────────────────────────────────────────────────────────────

def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(str(pdf_path))
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


def split_into_chapters(pages: dict[int, str]) -> list[tuple[str, str]]:
    CHARS = "一二三四五六七八九十"
    chapter_starts: dict[str, int] = {}
    current: str | None = None
    for pg in sorted(pages):
        m = re.search(r"第([一二三四五六七八九十]+)章", pages[pg])
        if m:
            ch = m.group(1)
            if ch != current:
                current = ch
                chapter_starts.setdefault(ch, pg)
    if not chapter_starts:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]
    ordered = sorted(chapter_starts.items(), key=lambda x: CHARS.find(x[0]) if x[0] in CHARS else 99)
    pg_sorted = sorted(pages)
    chapters: list[tuple[str, str]] = []
    for i, (ch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        chapters.append((f"第{ch}章", text))
    return chapters


# ── LLM 调用（Ollama OpenAI 兼容端点）───────────────────────────────────────

def llm_extract(client: httpx.Client, model: str, chapter_name: str,
                text_chunk: str, part_hint: str = "") -> dict:
    user = (f"{chapter_name}{part_hint} 正文内容（{len(text_chunk)}字符）：\n\n"
            f"{text_chunk}\n\n"
            "请提取所有KU（含物理模型和实验类），聚成KC，标前置依赖和适用条件。"
            "只输出JSON，不加任何其他文字。")

    # 最多重试 2 次（本地模型 JSON 截断率较高）
    for attempt in range(2):
        try:
            resp = client.post(
                f"{OLLAMA}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": LLM_SYSTEM},
                        {"role": "user",   "content": user},
                    ],
                    "temperature": 0.05,
                    "max_tokens": 6000,
                    "stream": False,
                },
                timeout=300,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            # 去掉可能的 markdown 代码块
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
            raw = raw.strip()
            # 找 JSON 对象
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except json.JSONDecodeError as e:
            if attempt == 0:
                print(f"    [JSON 截断，重试] {e}", flush=True)
                continue
            print(f"    [JSON 仍截断，跳过] {e}", flush=True)
        except Exception as e:
            print(f"    [LLM 错误] {e}", flush=True)
            break
    return {}


def extract_all_kus(client: httpx.Client, model: str,
                    chapters: list[tuple[str, str]],
                    limit: int | None = None) -> list[dict]:
    all_kus: list[dict] = []
    chapters_to_run = chapters[:limit] if limit else chapters

    for ch_name, ch_text in chapters_to_run:
        if not ch_text.strip():
            continue
        parts = []
        if len(ch_text) <= CHUNK:
            parts = [ch_text]
        else:
            n = (len(ch_text) + CHUNK - 1) // CHUNK
            for i in range(min(n, 6)):
                parts.append(ch_text[i * CHUNK: (i + 1) * CHUNK])

        for pi, part in enumerate(parts):
            hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
            t0 = time.time()
            print(f"  LLM: {ch_name}{hint} ({len(part)}字) ...", end="", flush=True)
            data = llm_extract(client, model, ch_name, part, hint)
            elapsed = time.time() - t0
            kus = data.get("kus", [])
            kcs = data.get("kcs", [])
            print(f" {len(kus)}KU  {elapsed:.0f}s", flush=True)

            ku_kc: dict[str, list[str]] = {}
            for kc in kcs:
                for kid in kc.get("ku_ids", []):
                    ku_kc.setdefault(kid, []).append(kc.get("name", ""))

            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            for ku in kus:
                ku["_chapter"] = ch_name
                ku["_kcs"] = ku_kc.get(ku.get("id", ""), []) or ["综合知识"]
                kt = ku.get("ku_type", "physical_concept")
                ku["ku_type"] = kt if kt in VALID_KU_TYPES else "physical_concept"
                resolved = [id_to_name.get(p, p) for p in ku.get("prerequisites", [])]
                ku["prerequisites"] = [r for r in resolved if r]
            all_kus.extend(kus)

    return all_kus


def dedup_kus(kus: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for ku in kus:
        key = ku.get("name", "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ku)
    return out


# ── DB 入库（与 DeepSeek 版完全一致）────────────────────────────────────────

def pg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert_cluster(conn: asyncpg.Connection, tb_id: str, kc_name: str, order: int) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", kc_name)[:40].strip("-").lower()
    kc_id = f"{tb_id}-kc-{slug}"
    await conn.execute(
        "INSERT INTO knowledge_clusters (id, textbook_id, name, display_order) "
        "VALUES ($1,$2,$3,$4) ON CONFLICT (id) DO NOTHING",
        kc_id, tb_id, kc_name, order,
    )
    return kc_id


async def upsert_ku(conn: asyncpg.Connection, tb_id: str, cluster_id: str, ku: dict) -> str:
    slug  = re.sub(r"[^\w一-鿿]", "-", ku["name"])[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff  = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
    prereqs  = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type  = ku.get("ku_type", "physical_concept")
    desc_parts = []
    if ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("applicable_conditions") and ku["applicable_conditions"] not in ("无特殊限制", ""):
        desc_parts.append(f"【适用条件】{ku['applicable_conditions']}")
    if ku.get("experiment_meta") and isinstance(ku["experiment_meta"], dict):
        em = ku["experiment_meta"]
        desc_parts.append(
            f"【实验】目的：{em.get('purpose','')}；原理：{em.get('principle','')}；"
            f"器材：{em.get('instruments','')}；步骤：{em.get('key_steps','')}；"
            f"数据处理：{em.get('data_method','')}"
        )
    description = "\n".join(desc_parts) or None
    await conn.execute(
        "INSERT INTO knowledge_units "
        "(id,textbook_id,cluster_id,name,description,prerequisites,related_kus,"
        " difficulty,exam_frequency,question_types,ku_type,mastery_levels) "
        "VALUES ($1,$2,$3,$4,$5,$6,'[]'::jsonb,$7,'mid','[]'::jsonb,$8,'[]'::jsonb) "
        "ON CONFLICT (id) DO NOTHING",
        ku_id, tb_id, cluster_id,
        ku["name"], description, prereqs, diff, ku_type,
    )
    return ku_id


async def store_kus(conn: asyncpg.Connection, tb_id: str, kus: list[dict]) -> int:
    kc_map: dict[str, str] = {}
    order = 1
    for ku in kus:
        for kc_name in ku.get("_kcs", []):
            if kc_name not in kc_map:
                kc_map[kc_name] = await upsert_cluster(conn, tb_id, kc_name, order)
                order += 1
    fallback = list(kc_map.values())[0] if kc_map else await upsert_cluster(conn, tb_id, "综合知识", 999)
    stored = 0
    for ku in kus:
        cluster_id = kc_map.get((ku.get("_kcs") or ["综合知识"])[0], fallback)
        await upsert_ku(conn, tb_id, cluster_id, ku)
        stored += 1
    return stored


# ── 报告 ─────────────────────────────────────────────────────────────────────

def make_report(kus: list[dict], model: str, elapsed: float,
                json_errors: int, total_chunks: int) -> dict:
    from collections import Counter
    type_cnt = dict(Counter(ku.get("ku_type") for ku in kus))

    # 每类取 2 个样本
    samples: dict[str, list[dict]] = {}
    for ku in kus:
        kt = ku.get("ku_type", "?")
        if len(samples.get(kt, [])) < 2:
            samples.setdefault(kt, []).append({
                "name":   ku.get("name"),
                "ku_type": kt,
                "core":   ku.get("core", ""),
                "applicable_conditions": ku.get("applicable_conditions", ""),
                "prerequisites": ku.get("prerequisites", []),
                "difficulty": ku.get("difficulty"),
                "experiment_meta": ku.get("experiment_meta"),
            })

    return {
        "model": model,
        "book": BOOK["title"],
        "tb_id": BOOK["tb_id"],
        "elapsed_s": round(elapsed),
        "total_chunks": total_chunks,
        "json_errors": json_errors,
        "ku_total": len(kus),
        "ku_type_distribution": type_cnt,
        "samples_by_type": samples,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def main(model: str, dry_run: bool, limit: int | None, out_file: str) -> None:
    pdf_path = PDF_DIR / BOOK["filename"]
    if not pdf_path.exists():
        sys.exit(f"PDF 不存在: {pdf_path}")

    print(f"→ {BOOK['title']}  ({pdf_path.stat().st_size//1024//1024}MB)  模型: {model}", flush=True)

    pages    = extract_page_texts(pdf_path)
    chapters = split_into_chapters(pages)
    total_chars = sum(len(t) for _, t in chapters)
    print(f"  {len(chapters)} 章节, {total_chars} 字符", flush=True)
    for cn, ct in chapters:
        print(f"    {cn}: {len(ct)} 字符", flush=True)

    # 统计 total_chunks
    total_chunks = sum(
        max(1, (len(ct) + CHUNK - 1) // CHUNK)
        for _, ct in (chapters[:limit] if limit else chapters)
        if ct.strip()
    )
    print(f"  预计 {total_chunks} 个 LLM 调用", flush=True)

    client = httpx.Client(timeout=300)
    json_errors: list[int] = [0]

    # Monkey-patch to count errors
    _orig = llm_extract
    def counted_extract(c, m, ch, txt, hint=""):
        r = _orig(c, m, ch, txt, hint)
        if not r:
            json_errors[0] += 1
        return r

    t0 = time.time()
    try:
        kus_raw = extract_all_kus(client, model, chapters, limit=limit)
    finally:
        client.close()
    elapsed = time.time() - t0

    kus = dedup_kus(kus_raw)
    print(f"\n  原始 {len(kus_raw)} KU → 去重 {len(kus)} KU  ({elapsed:.0f}s)", flush=True)

    report = make_report(kus, model, elapsed, json_errors[0], total_chunks)

    # 写 JSON 输出
    out_path = Path(out_file)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  报告已写入: {out_path}", flush=True)

    # 打印摘要
    print(f"\n{'='*60}", flush=True)
    print(f"  模型: {model}", flush=True)
    print(f"  KU总数: {kus} 个" if False else f"  KU总数: {len(kus)} 个", flush=True)
    print(f"  耗时: {elapsed:.0f}s  JSON错误: {json_errors[0]}/{total_chunks}", flush=True)
    print("  KU类型分布:", flush=True)
    from collections import Counter
    for kt, cnt in sorted(Counter(ku.get("ku_type") for ku in kus).items(), key=lambda x: -x[1]):
        print(f"    {kt:<22}: {cnt}", flush=True)

    # 展示每类 2 个样本
    print("\n  ── 样本 ──", flush=True)
    shown: dict[str, int] = {}
    for ku in kus:
        kt = ku.get("ku_type", "?")
        if shown.get(kt, 0) >= 2:
            continue
        shown[kt] = shown.get(kt, 0) + 1
        print(f"\n  [{kt}] {ku.get('name')}", flush=True)
        print(f"    core:       {str(ku.get('core',''))[:80]}", flush=True)
        print(f"    conditions: {str(ku.get('applicable_conditions',''))[:70]}", flush=True)
        em = ku.get("experiment_meta")
        if em and isinstance(em, dict):
            print(f"    实验目的:   {em.get('purpose','')[:60]}", flush=True)
            print(f"    实验原理:   {em.get('principle','')[:60]}", flush=True)
        print(f"    prereqs:    {ku.get('prerequisites',[])}", flush=True)
        print(f"    difficulty: {ku.get('difficulty')}", flush=True)
    print(f"{'='*60}", flush=True)

    if not dry_run:
        conn = await asyncpg.connect(pg_dsn(DB_URL))
        try:
            stored = await store_kus(conn, BOOK["tb_id"], kus)
        finally:
            await conn.close()
        print(f"\n  ✅ 入库完成: {stored} KU", flush=True)
    else:
        print("\n  [DRY-RUN] 未入库。", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:7b",
                    choices=["qwen2.5:7b", "qwen3.5:9b", "qwen3.5:4b", "gemma4:e4b"],
                    help="本地 Ollama 模型")
    ap.add_argument("--no-dry-run", action="store_true", help="实际入库（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前N个章节")
    ap.add_argument("--out", default="scripts/physics_bx2_local_7b.json",
                    help="输出报告 JSON 路径")
    args = ap.parse_args()
    asyncio.run(main(
        model=args.model,
        dry_run=not args.no_dry_run,
        limit=args.limit,
        out_file=args.out,
    ))
